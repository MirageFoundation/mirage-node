/* global BigInt */
import { updateNotification } from "../utils/notifications.js";
import Storage from './Storage';
import seedVault from './SeedVault';
import { getPublicKey as secp256k1GetPublicKey } from '@noble/secp256k1';
import { derivePrivateKeyFromSeed, derivePublicKeyFromSeed } from './CryptoUtils.js';
import Api from '../lib/api';

const ALLOWED_TAGS = new Set(["", "sensitive", "porn", "gore", "violence", "death"]);

let __CosmSecp256k1 = null;
let __CosmSha256 = null;
async function ensureCosmCrypto() {
    if (!__CosmSecp256k1 || !__CosmSha256) {
        const mod = await import('@cosmjs/crypto');
        __CosmSecp256k1 = mod.Secp256k1;
        __CosmSha256 = mod.sha256;
    }
}

function requirePowBaseBits(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || !Number.isInteger(num) || num <= 0) {
        try { console.error('[PoW] invalid pow_base_bits', { value }); } catch (_) { }
        throw new Error('pow_base_bits missing or invalid');
    }
    return num;
}

function requirePowDifficulty(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || !Number.isInteger(num) || num < 0) {
        try { console.error('[PoW] invalid pow_difficulty', { value }); } catch (_) { }
        throw new Error('pow_difficulty missing or invalid');
    }
    return num;
}

function requirePowFactor(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0 || num > 1) {
        try { console.error('[PoW] invalid pow_factor', { value }); } catch (_) { }
        throw new Error('pow_factor missing or invalid');
    }
    return num;
}

function requireTxDifficulty(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || !Number.isInteger(num) || num < 0) {
        throw new Error('pow_difficulty missing or invalid');
    }
    return num;
}

function resolveTxDifficulty(tx) {
    if (typeof tx?.pow_difficulty !== 'undefined') return requireTxDifficulty(tx.pow_difficulty);
    if (typeof tx?.difficulty !== 'undefined') return requireTxDifficulty(tx.difficulty);
    throw new Error('pow_difficulty missing or invalid');
}


class TransactionHandler {
    constructor() {
        if (!TransactionHandler.instance) {
            this.transactions = [];
            this.isProcessing = false;

            this.totalTransactions = 0;
            this.processedTransactions = 0;

            this.setWarnOnLeave = null;
            this.updatePost = null;
            this.getPost = null;
            this.txStatusCallback = null;

            this.pendingTx = [];
            this.txPollTimer = null;
            this.pendingPosts = new Map();

            this.lastOnchainBalanceUmirage = 0;

            // Track in-flight follow/unfollow operations with queue position and action type
            // Map<key, { action: 'follow'|'unfollow', type: 'user'|'topic', target: string, queuePosition: number }>
            this.pendingFollows = new Map();
            this._followListeners = new Set();

            // Track in-flight votes by post ID: Map<postId, { direction: number, queuePosition: number }>
            this.pendingVotes = new Map();
            this._voteListeners = new Set();

            // Vote detail polling can overlap when users vote quickly.
            // Track the latest vote tx per target and cancel/ignore stale poll loops.
            this._voteDetailsPollToken = new Map();   // Map<targetLower, number>
            this._latestVoteTxByTarget = new Map();   // Map<targetLower, txHashLower>

            // Debug counter for tracking transactions
            this._txCounter = 0;

            // Enhanced status tracking
            this._currentStatus = 'idle'; // idle, queued, processing, submitting
            this._statusStartTime = null;
            this._statusListeners = new Set();
            this._statusUpdateInterval = null;

            TransactionHandler.instance = this;
        }
        return TransactionHandler.instance;
    }

    _persistUserBalance(balanceVal, { normalizeStorage = false, updateLastOnchain = true } = {}) {
        if (balanceVal === undefined || balanceVal === null) return;
        if (normalizeStorage) {
            const balanceNum = Number(balanceVal);
            const normalized = Number.isFinite(balanceNum) ? Math.max(0, Math.trunc(balanceNum)) : 0;
            if (updateLastOnchain) {
                this.lastOnchainBalanceUmirage = normalized;
            }
            Storage.save('user_balance', String(normalized));
            window.dispatchEvent(new CustomEvent('balanceUpdated', { detail: normalized }));
            return;
        }
        Storage.save('user_balance', String(balanceVal));
        const balanceNum = Number(balanceVal);
        if (updateLastOnchain && Number.isFinite(balanceNum)) {
            this.lastOnchainBalanceUmirage = Math.max(0, Math.trunc(balanceNum));
        }
        window.dispatchEvent(new CustomEvent('balanceUpdated', { detail: balanceVal }));
    }

    // Vote tracking methods
    addVoteListener(callback) {
        if (typeof callback === 'function') {
            this._voteListeners.add(callback);
        }
        return () => this._voteListeners.delete(callback);
    }

    _notifyVoteListeners() {
        const pending = this.getPendingVotes();
        this._voteListeners.forEach(cb => {
            try { cb(pending); } catch (_) { }
        });
    }

    getPendingVotes() {
        const result = {};
        this.pendingVotes.forEach((value, key) => {
            result[key] = value;
        });
        return result;
    }

    isPendingVote(postId) {
        const key = String(postId || '').toLowerCase();
        return this.pendingVotes.has(key);
    }

    getPendingVoteDirection(postId) {
        const key = String(postId || '').toLowerCase();
        const entry = this.pendingVotes.get(key);
        return entry ? entry.direction : null;
    }

    // Follow tracking methods
    addFollowListener(callback) {
        if (typeof callback === 'function') {
            this._followListeners.add(callback);
        }
        return () => this._followListeners.delete(callback);
    }

    _notifyFollowListeners() {
        const pending = this.getPendingFollows();
        this._followListeners.forEach(cb => {
            try { cb(pending); } catch (_) { }
        });
    }

    getPendingFollows() {
        const result = {};
        this.pendingFollows.forEach((value, key) => {
            result[key] = value;
        });
        return result;
    }

    isPendingFollow(type, target) {
        const key = `${type}:${String(target || '').toLowerCase()}`;
        return this.pendingFollows.has(key);
    }

    getPendingFollowInfo(type, target) {
        const key = `${type}:${String(target || '').toLowerCase()}`;
        return this.pendingFollows.get(key) || null;
    }

    addStatusListener(callback) {
        if (typeof callback === 'function') {
            this._statusListeners.add(callback);
        }
        return () => this._statusListeners.delete(callback);
    }

    _notifyStatusListeners() {
        const status = this.getQueueStatus();
        this._statusListeners.forEach(cb => {
            try { cb(status); } catch (_) { }
        });
    }

    _startStatusUpdates() {
        if (this._statusUpdateInterval) return;
        this._statusUpdateInterval = setInterval(() => {
            this._notifyStatusListeners();
        }, 500);
    }

    _stopStatusUpdates() {
        if (this._statusUpdateInterval) {
            clearInterval(this._statusUpdateInterval);
            this._statusUpdateInterval = null;
        }
        this._notifyStatusListeners();
    }

    getQueueStatus() {
        const elapsed = this._statusStartTime ? (Date.now() - this._statusStartTime) / 1000 : 0;
        return {
            status: this._currentStatus,
            position: this.processedTransactions,
            total: this.totalTransactions,
            elapsed: elapsed,
            isActive: this._currentStatus !== 'idle'
        };
    }

    getNextQueuePosition() {
        return this.totalTransactions + 1;
    }

    _updateStatus(status) {
        const prevStatus = this._currentStatus;
        this._currentStatus = status;
        if (status !== 'idle' && (prevStatus === 'idle' || !this._statusStartTime)) {
            this._statusStartTime = Date.now();
            this._startStatusUpdates();
        } else if (status === 'idle') {
            this._statusStartTime = null;
            this._stopStatusUpdates();
        }
        this._notifyStatusListeners();
    }

    /**
     * Poll for vote details after indexing and show weight in toast.
     * Also stores the user_weight for accurate display calculations.
     * @param {string} txHash
     * @param {string=} targetKeyLower
     * @param {number=} token
     */
    async _pollVoteDetails(txHash, targetKeyLower = null, token = null) {
        // Wait 4 seconds before first poll (give indexer time to process)
        await new Promise(r => setTimeout(r, 4000));

        const maxAttempts = 5;
        const delayMs = 2000;

        for (let i = 0; i < maxAttempts; i++) {
            if (targetKeyLower) {
                const curToken = this._voteDetailsPollToken.get(targetKeyLower);
                if (token !== null && curToken !== token) return;
                const latestTx = this._latestVoteTxByTarget.get(targetKeyLower);
                if (latestTx && latestTx !== String(txHash).toLowerCase()) return;
            }
            try {
                const res = await Api.get('get_tx_status', { hash: txHash }, { timeoutMs: 5000 });
                if (res && res.found && res.indexed && res.tx_type === 'vote' && res.details) {
                    const details = res.details;
                    const weight = details.user_weight;
                    const vote = details.user_vote;
                    const target = details.target || '';
                    const dir = vote > 0 ? '+1' : (vote < 0 ? '-1' : '0');

                    // Update post's points in state with server's actual value for faster UI refresh
                    if (target) {
                        const tLower = String(target).toLowerCase();
                        if (targetKeyLower) {
                            const curToken = this._voteDetailsPollToken.get(targetKeyLower);
                            if (token !== null && curToken !== token) return;
                            const latestTx = this._latestVoteTxByTarget.get(targetKeyLower);
                            if (latestTx && latestTx !== String(txHash).toLowerCase()) return;
                            const latestForReturned = this._latestVoteTxByTarget.get(tLower);
                            if (latestForReturned && latestForReturned !== String(txHash).toLowerCase()) return;
                        }
                        const serverPoints = details.target_points;
                        if (typeof serverPoints === 'number' && this.updatePost && this.getPost) {
                            let postKey = tLower;
                            if (!this.getPost(tLower)) {
                                const exactKey = String(target).trim();
                                if (this.getPost(exactKey)) postKey = exactKey;
                            }
                            // Update points, direction, and user_weight from server
                            const serverDir = vote > 0 ? 1 : (vote < 0 ? -1 : 0);
                            const updateData = { points: serverPoints, direction: serverDir };
                            // Include user_weight so VoteSection formula calculates correctly
                            if (typeof weight === 'number') {
                                updateData.user_weight = weight;
                            }
                            this.updatePost(postKey, updateData);
                        }
                        this._notifyVoteListeners();
                    }

                    // Log full details to console for debugging (no toast)
                    console.log('Vote indexed:', {
                        txhash: txHash,
                        target: target,
                        direction: dir,
                        user_vote: vote,
                        user_weight: weight,
                        target_points: details.target_points,
                    });
                    return;
                }
            } catch (_) {
                // Ignore errors, keep polling
            }
            // Wait before next attempt
            await new Promise(r => setTimeout(r, delayMs));
        }
        // Timeout - vote not indexed yet, that's fine
    }

    _startVoteDetailsPoll(txHash, targetRaw) {
        const tLower = String(targetRaw || '').trim().toLowerCase();
        if (!tLower || !txHash) {
            this._pollVoteDetails(txHash);
            return;
        }
        const nextToken = (this._voteDetailsPollToken.get(tLower) || 0) + 1;
        this._voteDetailsPollToken.set(tLower, nextToken);
        this._latestVoteTxByTarget.set(tLower, String(txHash).toLowerCase());
        this._pollVoteDetails(txHash, tLower, nextToken);
    }

    // Polling removed: we use tx_hash immediately from relay response

    /**
     * @param {string} usernameRaw
     * @param {string} [inviteCode] - Optional invite code used for account creation
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async createUser(usernameRaw, inviteCode = "") {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const username = String(usernameRaw || "").trim();
            if (!username) return { success: false, error: "empty username" };

            // Determine subscriber path
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Fetching transaction parameters");
                const statusData = await Api.get('get_parameters', publicKey ? { address: publicKey } : undefined);
                last_block_hash = statusData.last_block_hash;
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);

                try {
                    const onChainBalance = Number(typeof statusData.balance !== 'undefined' ? statusData.balance : Storage.load('user_balance', '0'));
                    this._persistUserBalance(onChainBalance, { normalizeStorage: true });
                } catch (_) { }
            }

            const tx = {
                action: 'set_username',
                username,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                // Use a slightly past timestamp to avoid envelope_timestamp-in-future due to clock skew
                timestamp: Math.max(0, Date.now() - 15000),
                // Include invite code if provided (backend marks it as used)
                invite_code: inviteCode || "",
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    async setUsername(usernameRaw) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const username = String(usernameRaw || "").trim();
            if (!username) return { success: false, error: "empty username" };

            // Subscribers do not need parameters; free users do
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            if (userLevel === 0) {
                updateNotification("Preparing username change");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
                try {
                    const onChainBalance = Number(typeof statusData.balance !== 'undefined' ? statusData.balance : Storage.load('user_balance', '0'));
                    this._persistUserBalance(onChainBalance, { normalizeStorage: true });
                } catch (_) { }
            }

            const tx = {
                action: 'set_username',
                username,
                last_block_hash: userLevel >= 1 ? "" : last_block_hash,
                pow_difficulty: userLevel >= 1 ? 0 : pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${userLevel >= 1 ? "" : last_block_hash}:0`; // Challenge format required

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    /**
     * Block or unblock a post by its txhash
     * @param {string} txhash - The post txhash to block/unblock
     * @param {boolean} block - true to block, false to unblock
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async blockPost(txhash) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            if (!txhashTrimmed) return { success: false, error: "empty txhash" };

            // Check if post is already blocked
            try {
                const blocked = await Api.get('get_user_blocked', { address: publicKey }, { timeoutMs: 5000 });
                const blockedPosts = (blocked?.blocked_posts || []).map(p => String(p).toLowerCase());
                if (blockedPosts.includes(txhashTrimmed)) {
                    return { success: false, error: "post is already blocked" };
                }
            } catch (_) { }

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Blocking post");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
                try {
                    const onChainBalance = Number(typeof statusData.balance !== 'undefined' ? statusData.balance : Storage.load('user_balance', '0'));
                    this._persistUserBalance(onChainBalance, { normalizeStorage: true });
                } catch (_) { }
            }

            const tx = {
                action: 'block_post',
                target: txhashTrimmed,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    async unblockPost(txhash) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            if (!txhashTrimmed) return { success: false, error: "empty txhash" };

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Unblocking post");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
            }

            const tx = {
                action: 'unblock_post',
                target: txhashTrimmed,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    async blockUser(address) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const addressTrimmed = String(address || "").trim().toLowerCase();
            if (!addressTrimmed) return { success: false, error: "empty address" };

            // Check if user is already blocked
            try {
                const blocked = await Api.get('get_user_blocked', { address: publicKey }, { timeoutMs: 5000 });
                const blockedUsers = (blocked?.blocked_users || []).map(u => String(u).toLowerCase());
                if (blockedUsers.includes(addressTrimmed)) {
                    return { success: false, error: "user is already blocked" };
                }
            } catch (_) { }

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Blocking user");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
            }

            const tx = {
                action: 'block_user',
                target: addressTrimmed,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    async unblockUser(address) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const addressTrimmed = String(address || "").trim().toLowerCase();
            if (!addressTrimmed) return { success: false, error: "empty address" };

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Unblocking user");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
            }

            const tx = {
                action: 'unblock_user',
                target: addressTrimmed,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    async blockTopic(topic) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const topicTrimmed = String(topic || "").trim().toLowerCase();
            if (!topicTrimmed) return { success: false, error: "empty topic" };

            // Check if topic is already blocked
            try {
                const blocked = await Api.get('get_user_blocked', { address: publicKey }, { timeoutMs: 5000 });
                const blockedTopics = (blocked?.blocked_topics || []).map(t => String(t).toLowerCase());
                if (blockedTopics.includes(topicTrimmed)) {
                    return { success: false, error: "topic is already blocked" };
                }
            } catch (_) { }

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Blocking topic");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
                try {
                    const onChainBalance = Number(typeof statusData.balance !== 'undefined' ? statusData.balance : Storage.load('user_balance', '0'));
                    this._persistUserBalance(onChainBalance, { normalizeStorage: true });
                } catch (_) { }
            }

            const tx = {
                action: 'block_topic',
                topic: topicTrimmed,
                target: "",
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    async unblockTopic(topic) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const topicTrimmed = String(topic || "").trim().toLowerCase();
            if (!topicTrimmed) return { success: false, error: "empty topic" };

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Unblocking topic");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
            }

            const tx = {
                action: 'unblock_topic',
                topic: topicTrimmed,
                target: "",
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    followUser(userAddress) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve({ success: false, error: "Not logged in" });
        }

        const userTrimmed = String(userAddress || "").trim().toLowerCase();
        if (!userTrimmed) {
            return Promise.resolve({ success: false, error: "empty user address" });
        }

        const key = `user:${userTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve({ success: false, error: "follow user already in progress" });
        }

        const queuePosition = this.totalTransactions + 1;
        this.pendingFollows.set(key, { action: 'follow', type: 'user', target: userTrimmed, queuePosition });
        this._notifyFollowListeners();

        const baseTx = {
            action: 'follow_user',
            userId: publicKey,
            user: userTrimmed,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                this.pendingFollows.delete(key);
                this._notifyFollowListeners();
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _followKey: key };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    unfollowUser(userAddress) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve({ success: false, error: "Not logged in" });
        }

        const userTrimmed = String(userAddress || "").trim().toLowerCase();
        if (!userTrimmed) {
            return Promise.resolve({ success: false, error: "empty user address" });
        }

        const key = `user:${userTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve({ success: false, error: "unfollow user already in progress" });
        }

        const queuePosition = this.totalTransactions + 1;
        this.pendingFollows.set(key, { action: 'unfollow', type: 'user', target: userTrimmed, queuePosition });
        this._notifyFollowListeners();

        const baseTx = {
            action: 'unfollow_user',
            userId: publicKey,
            user: userTrimmed,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                this.pendingFollows.delete(key);
                this._notifyFollowListeners();
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _followKey: key };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    followTopic(topic) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve({ success: false, error: "Not logged in" });
        }

        const topicTrimmed = String(topic || "").trim().toLowerCase();
        if (!topicTrimmed) {
            return Promise.resolve({ success: false, error: "empty topic" });
        }

        const key = `topic:${topicTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve({ success: false, error: "follow topic already in progress" });
        }

        const queuePosition = this.totalTransactions + 1;
        this.pendingFollows.set(key, { action: 'follow', type: 'topic', target: topicTrimmed, queuePosition });
        this._notifyFollowListeners();

        const baseTx = {
            action: 'follow_topic',
            userId: publicKey,
            topic: topicTrimmed,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                this.pendingFollows.delete(key);
                this._notifyFollowListeners();
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _followKey: key };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    unfollowTopic(topic) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve({ success: false, error: "Not logged in" });
        }

        const topicTrimmed = String(topic || "").trim().toLowerCase();
        if (!topicTrimmed) {
            return Promise.resolve({ success: false, error: "empty topic" });
        }

        const key = `topic:${topicTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve({ success: false, error: "unfollow topic already in progress" });
        }

        const queuePosition = this.totalTransactions + 1;
        this.pendingFollows.set(key, { action: 'unfollow', type: 'topic', target: topicTrimmed, queuePosition });
        this._notifyFollowListeners();

        const baseTx = {
            action: 'unfollow_topic',
            userId: publicKey,
            topic: topicTrimmed,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                this.pendingFollows.delete(key);
                this._notifyFollowListeners();
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _followKey: key };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    /**
     * Report a post by txhash with a short reason. Requires PoW for level 0 users.
     * @param {string} txhash
     * @param {string} reason
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, id?: number}>}
     */
    async reportPost(txhash, reason) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            const why = String(reason || "").trim();
            if (!txhashTrimmed) return { success: false, error: "empty target" };
            if (!why) return { success: false, error: "empty reason" };

            updateNotification("Preparing report");
            const [statusData] = await Promise.all([
                Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
            ]);
            const last_block_hash = statusData.last_block_hash;
            let pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
            const pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
            const pow_factor = requirePowFactor(statusData.pow_factor);
            // Level >= 1 users don't need PoW
            const userLevel = Number(statusData.user_level !== undefined ? statusData.user_level : Storage.load('user_level', '0')) || 0;
            if (userLevel >= 1) {
                pow_difficulty = 0;
            }

            const tx = {
                action: 'report',
                target: txhashTrimmed,
                reason: why,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, true);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    /**
     * Send tokens to another address
     * @param {string} targetAddress - The recipient address
     * @param {number} amountMirage - Amount in MIRAGE to send
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async sendTokens(targetAddress, amountMirage) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const targetTrimmed = String(targetAddress || "").trim().toLowerCase();

            if (!targetTrimmed || !amountMirage || amountMirage <= 0) {
                return { success: false, error: "Invalid recipient or amount" };
            }

            // Validate mirage1 address
            if (!targetTrimmed.startsWith("mirage1")) {
                return { success: false, error: "Recipient must be a mirage1 address" };
            }

            // Convert MIRAGE to umirage
            const amountUmirage = Math.floor(amountMirage * 1000000);
            if (amountUmirage < 1000) {
                return { success: false, error: "Minimum amount is 0.001 MIRAGE" };
            }

            updateNotification("Sending tokens");

            const [statusData] = await Promise.all([
                Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
            ]);
            let last_block_hash = statusData?.last_block_hash || "";
            let pow_difficulty = requirePowDifficulty(statusData?.pow_difficulty);
            const pow_base_bits = requirePowBaseBits(statusData?.pow_base_bits);
            const pow_factor = requirePowFactor(statusData?.pow_factor);
            const balance = statusData?.balance || 0;
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            if (userLevel >= 1) {
                pow_difficulty = 0;
                last_block_hash = "";
            }

            // Check balance for amount only (no gas fee for level >= 1 users)
            const totalNeeded = amountUmirage;

            if (balance < totalNeeded) {
                const haveM = (balance / 1000000).toFixed(3);
                const needM = (totalNeeded / 1000000).toFixed(3);
                return { success: false, error: `Insufficient balance. Have: ${haveM} MIRAGE, Need: ${needM} MIRAGE` };
            }

            const tx = {
                action: 'send_tokens',
                target: targetTrimmed,
                amount: amountUmirage,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    /**
     * Upgrade subscription level (tier)
     * @param {number} level - Target paid subscription level (1-3)
     * @param {number} monthlyFeeUmirage - The monthly fee in umirage for the target tier (unused, kept for API compatibility)
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async upgradeLevel(level, monthlyFeeUmirage) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const targetLevel = Number(level);

            if (targetLevel < 1 || targetLevel > 3) {
                return { success: false, error: "Invalid level (must be 1-3)" };
            }

            updateNotification("Upgrading subscription");

            // No need to fetch parameters for upgrade; chain determines tier fee server-side
            const last_block_hash = "";
            const tx = {
                action: 'upgrade_level',
                level: targetLevel,
                last_block_hash,
                pow_difficulty: 0, // PoW not allowed for upgrade
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const challenge = `${derivedAddress}:${last_block_hash}:0`;

            // Force fees mode (no PoW)
            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    /**
     * Set auto-renewal flag for the current subscription.
     * @param {boolean} autoRenew - true to enable auto-renewal, false to disable
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async setAutoRenewal(autoRenew) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const last_block_hash = "";
            const tx = {
                action: 'set_auto_renewal',
                auto_renew: Boolean(autoRenew),
                last_block_hash,
                pow_difficulty: 0,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const challenge = `${derivedAddress}:${last_block_hash}:0`;

            // Force fees mode (no PoW)
            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    /**
     * Bridge tokens via attested burn (e.g., Solana)
     * @param {string} destinationChain - Target chain ID (e.g., "solana")
     * @param {string} destinationAddress - Recipient address on target chain
     * @param {number} amountUmirage - Amount in umirage to burn and bridge
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, burn_tx_hash?: string, burn_sequence?: string|number|null, result?: any}>}
     */
    async bridgeBurn(destinationChain, destinationAddress, amountUmirage) {
        try {
            const seedPhrase = seedVault.getSeed() || "";

            const chain = String(destinationChain || "").trim().toLowerCase();
            if (!chain) return { success: false, error: "destination_chain required" };

            const address = String(destinationAddress || "").trim();
            if (!address) return { success: false, error: "destination_address required" };

            const amount = Number(amountUmirage) || 0;
            if (amount <= 0) return { success: false, error: "amount must be positive" };

            // Bridge burn never uses PoW - token transfers are self-authenticating
            // (you can't burn tokens you don't have)
            const tx = {
                action: 'bridge_burn',
                destination_chain: chain,
                destination_address: address,
                amount: amount,
                last_block_hash: "",
                pow_difficulty: 0,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const challenge = `${derivedAddress}:${tx.last_block_hash}:${tx.pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    /**
     * Delete a post or comment
     * @param {string} txhash - The transaction hash of the post/comment to delete
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async deletePost(txhash) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            if (!txhashTrimmed) return { success: false, error: "empty txhash" };

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                updateNotification("Deleting post");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
                try {
                    const onChainBalance = Number(typeof statusData.balance !== 'undefined' ? statusData.balance : Storage.load('user_balance', '0'));
                    this._persistUserBalance(onChainBalance, { normalizeStorage: true });
                } catch (_) { }
            }

            const tx = {
                action: 'delete_post',
                target: txhashTrimmed,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    /**
     * Edit an existing post/comment
     * @param {string} overrideId - txhash of the post/comment being edited
     * @param {{target?: string, topic?: string, title?: string, content: string, tag?: string, media?: string[]}} changes
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async editPost(overrideId, changes) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const overrideLower = String(overrideId || "").trim().toLowerCase();
            if (!overrideLower || overrideLower.length !== 64) return { success: false, error: "invalid override id" };
            const content = String(changes?.content || "").trim();
            const title = String(changes?.title || "").trim();
            const topic = String(changes?.topic || "").trim();
            const target = String(changes?.target || "").trim();
            const tagRaw = String(changes?.tag || "").trim().toLowerCase();
            const media = Array.isArray(changes?.media) ? changes.media : [];
            if (!ALLOWED_TAGS.has(tagRaw)) return { success: false, error: "invalid tag" };

            const userLevelE = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash_e = "";
            let pow_difficulty_e = 0;
            let pow_base_bits_e = 0;
            let pow_factor_e = 0;
            if (userLevelE === 0) {
                updateNotification("Preparing edit");
                const [statusData] = await Promise.all([
                    Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
                ]);
                last_block_hash_e = statusData.last_block_hash || "";
                pow_difficulty_e = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits_e = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor_e = requirePowFactor(statusData.pow_factor);
            }

            const tx = {
                action: 'edit_post',
                override: overrideLower,
                target,
                topic,
                title,
                content,
                tag: tagRaw,
                media,
                last_block_hash: last_block_hash_e,
                pow_difficulty: pow_difficulty_e,
                pow_base_bits: pow_base_bits_e,
                pow_factor: pow_factor_e,
                timestamp: Math.max(0, Date.now() - 15000),
            };
            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash_e}:${pow_difficulty_e}`;
            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }


    setWarnOnLeaveCallback(setWarnOnLeave) {
        this.setWarnOnLeave = setWarnOnLeave;
    }

    getPostCallback(getPost) {
        this.getPost = getPost;
    }

    updatePostCallback(updatePost) {
        this.updatePost = updatePost;
    }

    setTxStatusCallback(fn) {
        this.txStatusCallback = typeof fn === 'function' ? fn : null;
    }

    _setStatus(status) {
        // Map old statuses to new ones and update
        const statusMap = {
            'preparing': 'processing',
            'submitting': 'submitting',
            'idle': 'idle'
        };
        this._updateStatus(statusMap[status] || status);

        // Also call legacy callback if set
        if (!this.txStatusCallback) return;
        try {
            this.txStatusCallback(status);
        } catch (_) { }
    }

    calculateInitialVotes() {
        return 1;
    }

    /**
     * Cache chain governance params (from get_chain_config).
     * Stored in localStorage as 'chainConfig'.
     */
    cacheChainConfig(data) {
        if (!data || typeof data !== 'object') return;
        try {
            localStorage.setItem('chainConfig', JSON.stringify(data));
            Storage.save('chain_config_cached_at', String(Date.now()));
        } catch (_) { }
        console.debug('[TransactionHandler] cacheChainConfig', { keys: Object.keys(data) });
        window.dispatchEvent(new Event('chainConfigUpdated'));
    }

    /**
     * Cache per-node static settings (from get_node_config).
     * Stored in localStorage as 'nodeConfig'.
     */
    cacheNodeConfig(data) {
        if (!data || typeof data !== 'object') return;
        try {
            localStorage.setItem('nodeConfig', JSON.stringify(data));
            Storage.save('node_config_cached_at', String(Date.now()));
        } catch (_) { }
        console.debug('[TransactionHandler] cacheNodeConfig', { keys: Object.keys(data) });
        window.dispatchEvent(new Event('nodeConfigUpdated'));
    }

    /**
     * Cache user-specific data (from get_user_status).
     * Each field stored in its own key — no monolithic blob.
     */
    cacheUserStatus(data) {
        if (!data || typeof data !== 'object') return;
        if (data.username !== undefined) Storage.save('username', data.username);
        if (data.user_level !== undefined && data.user_level !== null) Storage.save('user_level', String(data.user_level));
        if (data.server_balance !== undefined) Storage.save('server_balance', String(data.server_balance));
        const balanceVal = data.balance !== undefined ? data.balance : data.user_balance;
        if (balanceVal !== undefined) {
            this._persistUserBalance(balanceVal);
        }
        console.debug('[TransactionHandler] cacheUserStatus', {
            hasUsername: data.username !== undefined,
            userLevel: data.user_level ?? null,
            hasBalance: balanceVal !== undefined,
        });
        window.dispatchEvent(new Event('userStatusUpdated'));
    }

    createVote(parentId, direction) {
        let action = "create_vote";

        let publicKey = Storage.load("publicKey", "");
        let seedPhrase = seedVault.getSeed() || "";
        if ((!publicKey) || (!seedPhrase)) {
            updateNotification("Not logged in");
            return Promise.resolve({ success: false, error: "Not logged in" });
        }

        const postKey = String(parentId || '').toLowerCase();

        // Check if vote already pending for this post
        if (this.pendingVotes.has(postKey)) {
            return Promise.resolve({ success: false, error: "Vote already pending" });
        }

        const baseTx = {
            action: action,
            userId: publicKey,
            parentId: parentId,
            direction: direction
        };

        // Track pending vote
        const queuePosition = this.totalTransactions + 1;
        this.pendingVotes.set(postKey, { direction, queuePosition });
        this._notifyVoteListeners();

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                // Clear pending vote when done
                this.pendingVotes.delete(postKey);
                this._notifyVoteListeners();
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _voteKey: postKey };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    createPost(topic, title, content, tag = "", media = []) {
        let action = "create_post";

        let publicKey = Storage.load("publicKey", "");
        let seedPhrase = seedVault.getSeed() || "";
        if ((!publicKey) || (!seedPhrase)) {
            updateNotification("Not logged in");
            return;
        }

        const cleanTag = typeof tag === 'string' ? tag.trim().toLowerCase() : "";
        if (!ALLOWED_TAGS.has(cleanTag)) {
            updateNotification("Invalid tag");
            return;
        }

        let transaction = {
            action: action,
            userId: publicKey,
            topic: topic,
            title: title,
            content: content,
            tag: cleanTag,
            media: Array.isArray(media) ? media : [],
        };

        this.transactions.push(transaction);
        this.totalTransactions += 1;
        this.processTransactions();
    }

    /**
     * Create a post and wait for completion (PoW + broadcast)
     * @param {string} topic
     * @param {string} title
     * @param {string} content
     * @param {string} tag
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string}>}
     */
    async createPostAsync(topic, title, content, tag = "", media = []) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            if (!publicKey || !seedPhrase) {
                return { success: false, error: "Not logged in" };
            }

            const cleanTag = typeof tag === 'string' ? tag.trim().toLowerCase() : "";
            if (!ALLOWED_TAGS.has(cleanTag)) {
                return { success: false, error: "invalid tag" };
            }

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                const statusData = await Api.get('get_parameters', publicKey ? { address: publicKey } : undefined);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
            }

            const tx = {
                action: 'create_post',
                userId: publicKey,
                topic,
                title,
                content,
                tag: cleanTag,
                media: Array.isArray(media) ? media : [],
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }

    createComment(parentId, content) {
        let action = "create_comment";

        let publicKey = Storage.load("publicKey", "");
        let seedPhrase = seedVault.getSeed() || "";
        if ((!publicKey) || (!seedPhrase)) {
            updateNotification("Not logged in");
            return;
        }

        let transaction = {
            action: action,
            userId: publicKey,

            parentId: parentId,
            content: content
        }

        this.transactions.push(transaction);
        this.totalTransactions += 1;
        this.processTransactions();
    }

    /**
     * Create a comment and wait for completion (PoW + broadcast)
     * @param {string} parentId - txhash of parent post/comment
     * @param {string} content
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string}>}
     */
    async createCommentAsync(parentId, content) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            if (!publicKey || !seedPhrase) {
                return { success: false, error: "Not logged in" };
            }

            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
                const statusData = await Api.get('get_parameters', publicKey ? { address: publicKey } : undefined);
                last_block_hash = statusData.last_block_hash || "";
                pow_difficulty = requirePowDifficulty(statusData.pow_difficulty);
                pow_base_bits = requirePowBaseBits(statusData.pow_base_bits);
                pow_factor = requirePowFactor(statusData.pow_factor);
            }

            const tx = {
                action: 'create_comment',
                userId: publicKey,
                parentId,
                target: parentId,
                content,
                last_block_hash,
                pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return { success: false, error: String(e?.message || e) };
        }
    }


    async processTransactions() {
        if (this.isProcessing) {
            // Still notify that we're queued
            if (this.transactions.length > 0 && this._currentStatus === 'idle') {
                this._updateStatus('queued');
            }
            return;
        }

        this.isProcessing = true;
        this.startTime = Date.now();
        this._statusStartTime = Date.now();

        let hadFailure = false;
        let hadQuestAction = false; // Track if any quest-relevant actions were processed
        while (this.transactions.length > 0) {
            // Get the next transaction  
            const queued = this.transactions.shift() || {};
            const _resolve = typeof queued._resolve === 'function' ? queued._resolve : null;
            const { _resolve: _ignored, _followKey: _ignored2, ...transaction } = queued;
            this.processedTransactions += 1;
            // Track quest-relevant actions
            if (transaction.action === 'create_vote' || transaction.action === 'create_post' || transaction.action === 'create_comment') {
                hadQuestAction = true;
            }


            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits_relay = 0;
            let pow_factor_relay = 0;
            const userLevelNow = Number(Storage.load('user_level', '0')) || 0;
            if (userLevelNow === 0) {
                // Free tier: must fetch real block hash for PoW validation
                updateNotification("Fetching transaction parameters");
                try {
                    const addrNow = Storage.load('publicKey', '');
                    const status = await Api.get('get_parameters', addrNow ? { address: addrNow } : undefined);
                    last_block_hash = status.last_block_hash || "";
                    pow_difficulty = requirePowDifficulty(status.pow_difficulty);
                    pow_base_bits_relay = requirePowBaseBits(status.pow_base_bits);
                    pow_factor_relay = requirePowFactor(status.pow_factor);
                    const onChainBalance = Math.max(0, Math.trunc(Number(typeof status.balance !== 'undefined' ? status.balance : Storage.load('user_balance', '0'))));
                    const prevOnChain = this.lastOnchainBalanceUmirage;
                    this.lastOnchainBalanceUmirage = onChainBalance;
                    if (this.pendingFeeUmirage > 0) {
                        const spentIncluded = onChainBalance <= Math.max(0, prevOnChain - this.pendingFeeUmirage);
                        if (spentIncluded) this.pendingFeeUmirage = 0;
                    }
                    const effectiveBalance = Math.max(0, this.lastOnchainBalanceUmirage - Math.max(0, this.pendingFeeUmirage));
                    this._persistUserBalance(effectiveBalance, { normalizeStorage: true, updateLastOnchain: false });
                } catch (error) {
                    const msg = (error && error.message) ? error.message : 'network error';
                    updateNotification(msg, 5, true);
                    return;
                }
            } else {
                // Subscribers: use timestamp as nonce for tx uniqueness (no PoW needed)
                last_block_hash = Date.now().toString(16).padStart(64, '0');
                pow_difficulty = 0;
            }

            let final_transaction = undefined;
            let challenge = undefined;
            // Derive signer address from current seed to ensure consistency with relay
            const seedPhrase = seedVault.getSeed() || "";
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return Storage.load('publicKey', ''); } })();
            if (derivedAddress && derivedAddress !== Storage.load('publicKey', '')) {
                try { Storage.save('publicKey', derivedAddress); } catch (_) { }
            }

            // Timestamp for canonical bytes (must match backend verification but avoid future skew)
            const txTimestamp = Math.max(0, Date.now() - 15000);

            // No optimistic UI flags; server-driven updates only
            if (transaction.action === "set_username") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    username: transaction.username,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "create_vote") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.parentId,
                    direction: Number(transaction.direction),
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "create_post") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: "",
                    topic: transaction.topic,
                    title: transaction.title,
                    content: transaction.content,
                    tag: transaction.tag || "",
                    media: Array.isArray(transaction.media) ? transaction.media : [],
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "create_comment") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.parentId,
                    title: "",
                    content: transaction.content,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "follow_user") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    user: transaction.user,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "unfollow_user") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    user: transaction.user,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "follow_topic") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    topic: transaction.topic,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "unfollow_topic") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    topic: transaction.topic,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }

            const privateKey = derivePrivateKeyFromSeed(seedPhrase);

            // Retry loop: PoW-related failures (difficulty changed between compute and submit)
            // warrant re-fetching params and recomputing PoW, up to 3 times.
            const MAX_POW_RETRIES = 3;
            const POW_RETRY_DELAY_MS = 3000;
            let result;
            let lastError = null;

            for (let attempt = 0; attempt <= MAX_POW_RETRIES; attempt++) {
                if (attempt > 0) {
                    // Re-fetch params and rebuild transaction for retry
                    updateNotification(`PoW stale — retrying (${attempt}/${MAX_POW_RETRIES})...`);
                    await new Promise(r => setTimeout(r, POW_RETRY_DELAY_MS));

                    if (userLevelNow === 0) {
                        try {
                            const addrRetry = Storage.load('publicKey', '');
                            const statusRetry = await Api.get('get_parameters', addrRetry ? { address: addrRetry } : undefined);
                            last_block_hash = statusRetry.last_block_hash || "";
                            pow_difficulty = requirePowDifficulty(statusRetry.pow_difficulty);
                            pow_base_bits_relay = requirePowBaseBits(statusRetry.pow_base_bits);
                            pow_factor_relay = requirePowFactor(statusRetry.pow_factor);
                        } catch (retryErr) {
                            continue; // param fetch failed, try again next iteration
                        }
                    }

                    // Rebuild the transaction with fresh params + timestamp
                    const retryTimestamp = Math.max(0, Date.now() - 15000);
                    if (final_transaction) {
                        final_transaction.last_block_hash = last_block_hash;
                        final_transaction.pow_difficulty = Number(pow_difficulty);
                        final_transaction.pow_base_bits = pow_base_bits_relay;
                        final_transaction.pow_factor = pow_factor_relay;
                        final_transaction.timestamp = retryTimestamp;
                    }
                    challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                }

                try {
                    result = await this.performTransaction(final_transaction, challenge, privateKey, derivedAddress);
                } catch (error) {
                    lastError = error;
                    const errMsg = String(error && error.message ? error.message : error);
                    // Retry on PoW-related failures (difficulty may have changed)
                    if (/insufficient pow/i.test(errMsg) || /precheck/i.test(errMsg) || /invalid last_block_hash/i.test(errMsg)) {
                        if (attempt < MAX_POW_RETRIES) continue;
                    }
                    // Non-retryable throw — handle below
                    break;
                }

                if (result && !result.success) {
                    const errMsg = String(result.error || '');
                    // Retry on PoW-related failures
                    if (/insufficient pow/i.test(errMsg) || /precheck/i.test(errMsg) || /invalid last_block_hash/i.test(errMsg)) {
                        if (attempt < MAX_POW_RETRIES) continue;
                    }
                }

                // Success or non-retryable failure — stop retrying
                break;
            }

            // Handle final failure (after all retries exhausted)
            if (lastError && (!result || !result.success)) {
                const errMsg = String(lastError && lastError.message ? lastError.message : lastError);
                if (/insufficient reserve/i.test(errMsg) || /subscription terminated/i.test(errMsg)) {
                    const grpcMatch = errMsg.match(/details\s*=\s*"([^"]+)"/);
                    const cleanMsg = grpcMatch && grpcMatch[1] ? grpcMatch[1] : 'Your subscription reserve is empty. Please top up your reserve funds or use PoW (free tier).';
                    updateNotification(cleanMsg, 10, true);
                } else if (/admin insufficient balance/i.test(errMsg)) {
                    updateNotification('Your account balance is too low to cover the transaction fee. Please fund your account.', 8, true);
                } else if (/insufficient funds/i.test(errMsg)) {
                    updateNotification('Unfortunately the node does not have enough gas available to complete this transaction.', 6, true);
                } else {
                    updateNotification(errMsg || 'Transaction failed', 5, true);
                }
                if (_resolve) _resolve({ success: false, error: errMsg });
                hadFailure = true;
                break;
            }
            if (!result || !result.success) {
                // Show a specific warning based on the failure reason
                const msg = String(result && result.error ? result.error : 'Transaction failed');
                // Check for subscription/reserve errors in the full error string
                if (/insufficient reserve/i.test(msg) || /subscription terminated/i.test(msg)) {
                    const grpcMatch = msg.match(/details\s*=\s*"([^"]+)"/);
                    const cleanMsg = grpcMatch && grpcMatch[1] ? grpcMatch[1] : 'Your subscription reserve is empty. Please top up your reserve funds or use PoW (free tier).';
                    updateNotification(cleanMsg, 10, true);
                } else if (/admin insufficient balance/i.test(msg)) {
                    updateNotification('Your account balance is too low to cover the transaction fee. Please fund your account.', 8, true);
                } else if (/insufficient funds/i.test(msg)) {
                    updateNotification('Unfortunately the node does not have enough gas available to complete this transaction.', 6, true);
                } else {
                    updateNotification(msg || 'Transaction failed', 5, true);
                }
                if (_resolve) _resolve(result || { success: false, error: msg });
                hadFailure = true;
                break;
            }

            if (_resolve) _resolve(result);

        }

        if (!hadFailure) {
            if (this.totalTransactions > 1) {
                updateNotification("All transactions submitted");
            } else {
                const userLevel = Number(Storage.load('user_level', '0')) || 0;
                if (userLevel >= 1) {
                    updateNotification("Transaction submitted");
                } else {
                    const elapsedTime = ((Date.now() - this.startTime) / 1000).toFixed(1);
                    updateNotification(`Transaction submitted (took ${elapsedTime}s)`);
                }
            }
            // Dispatch event for quest-relevant actions so quest progress can refresh
            if (hadQuestAction) {
                window.dispatchEvent(new CustomEvent('questActionCompleted', { detail: { batch: true } }));
            }
        }

        this.totalTransactions = 0;
        this.processedTransactions = 0;
        this.isProcessing = false;
        this._updateStatus('idle');

        if (this.setWarnOnLeave) {
            this.setWarnOnLeave(false);
        }
    }

    // Build canonical bytes for MsgPost
    canonicalPost({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, title, content, tag, media }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgPost\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);   // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]); // topic
        const tag102 = Uint8Array.from([102]);
        const tag103 = Uint8Array.from([103]);
        const tag104 = Uint8Array.from([104]); // tag field
        const tag105 = Uint8Array.from([105]); // media field (v1.12.0)

        const parts = [
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
            tag102, encStr(title || ""),
            tag103, encStr(content || ""),
            tag104, encStr(tag || ""),
        ];
        // Encode repeated media field (tag 105)
        for (const m of (media || [])) {
            parts.push(tag105);
            parts.push(encStr(m));
        }
        return concat(...parts);
    }

    // Build canonical bytes for MsgEdit (must match chain ante)
    canonicalEdit({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, title, content, tag, override, media }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgEdit\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);   // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]); // topic
        const tag102 = Uint8Array.from([102]);
        const tag103 = Uint8Array.from([103]);
        const tag104 = Uint8Array.from([104]); // tag field
        const tag105 = Uint8Array.from([105]); // override field
        const tag106 = Uint8Array.from([106]); // media field (v1.12.0+)
        const mediaParts = [];
        for (const m of (media || [])) {
            mediaParts.push(tag106);
            mediaParts.push(encStr(m));
        }

        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
            tag102, encStr(title || ""),
            tag103, encStr(content || ""),
            tag104, encStr(tag || ""),
            tag105, encStr(override || ""),
            ...mediaParts,
        );
    }

    // Build canonical bytes for MsgSetUsername (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalSetUsername({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, username }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetUsername\x00");
        const tag2 = Uint8Array.from([2]);    // envelope_pubkey (bytes)
        const tag3 = Uint8Array.from([3]);    // envelope_block_hash (string)
        const tag4 = Uint8Array.from([4]);    // envelope_difficulty (uvarint)
        const tag5 = Uint8Array.from([5]);    // envelope_pow (uvarint)
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp (uvarint)
        const tag100 = Uint8Array.from([100]); // target (string)
        const tag101 = Uint8Array.from([101]); // username (string)
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(username || ""),
        );
    }

    // Build canonical bytes for MsgSetModerators (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalSetModerators({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, moderators }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetModerators\x00");
        const tag2 = Uint8Array.from([2]);    // envelope_pubkey (bytes)
        const tag3 = Uint8Array.from([3]);    // envelope_block_hash (string)
        const tag4 = Uint8Array.from([4]);    // envelope_difficulty (uvarint)
        const tag5 = Uint8Array.from([5]);    // envelope_pow (uvarint)
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp (uvarint)
        const tag100 = Uint8Array.from([100]); // target (string)
        const tag101 = Uint8Array.from([101]); // moderators (repeated string)

        // Build envelope first
        const parts = [
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
        ];

        // Add repeated moderators field
        for (const mod of (moderators || [])) {
            parts.push(tag101);
            parts.push(encStr(mod));
        }

        return concat(...parts);
    }

    // Build canonical bytes for MsgFollowModerator
    canonicalFollowModerator({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, moderator }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgFollowModerator\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);    // envelope_pow
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(moderator || ""),
        );
    }

    // Build canonical bytes for MsgUnfollowModerator
    canonicalUnfollowModerator({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, moderator }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnfollowModerator\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);    // envelope_pow
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(moderator || ""),
        );
    }

    // Build canonical bytes for MsgFollowUser
    canonicalFollowUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, user }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgFollowUser\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(user || ""),
        );
    }

    // Build canonical bytes for MsgUnfollowUser
    canonicalUnfollowUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, user }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnfollowUser\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(user || ""),
        );
    }

    // Build canonical bytes for MsgFollowTopic
    canonicalFollowTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgFollowTopic\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgUnfollowTopic
    canonicalUnfollowTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnfollowTopic\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgUnblockPost
    canonicalUnblockPost({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockPost\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgUnblockUser
    canonicalUnblockUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockUser\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgBlockPost (v1.5: no block bool)
    canonicalBlockPost({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockPost\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgBlockUser (v1.5: no block bool)
    canonicalBlockUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockUser\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgBlockTopic
    canonicalBlockTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockTopic\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]); // topic
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgUnblockTopic
    canonicalUnblockTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockTopic\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]); // topic
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgDelete (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalDelete({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgDelete\x00");
        const tag2 = Uint8Array.from([2]);    // envelope_pubkey (bytes)
        const tag3 = Uint8Array.from([3]);    // envelope_block_hash (string)
        const tag4 = Uint8Array.from([4]);    // envelope_difficulty (uvarint)
        const tag5 = Uint8Array.from([5]);    // envelope_pow (uvarint)
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp (uvarint)
        const tag100 = Uint8Array.from([100]); // target (string)

        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgSendTokens (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalSendTokens({ pub_bytes, last_block_hash, difficulty, proof, timestamp, sender, target, amount }) {
        const uvarint = (n) => {
            const out = [];
            let v = (n >>> 0);
            while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
            out.push(v);
            return Uint8Array.from(out);
        };
        const uvarint64 = (n) => {
            const out = [];
            let v = BigInt(n || 0);
            while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
            out.push(Number(v));
            return Uint8Array.from(out);
        };
        const encStr = (s) => {
            const b = new TextEncoder().encode(s || "");
            return new Uint8Array([...uvarint(b.length), ...b]);
        };
        const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
        const hexToBytes = (hex) => {
            const h = (hex || "").replace(/^0x/i, "");
            if (!h || h.length % 2) return new Uint8Array(0);
            const arr = new Uint8Array(h.length / 2);
            for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
            return arr;
        };
        const concat = (...arrs) => {
            let total = 0; arrs.forEach(a => total += a.length);
            const out = new Uint8Array(total);
            let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
            return out;
        };
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgSendTokens\x00");
        const tag2 = Uint8Array.from([2]);    // envelope_pubkey (bytes)
        const tag3 = Uint8Array.from([3]);    // envelope_block_hash (string)
        const tag4 = Uint8Array.from([4]);    // envelope_difficulty (uvarint)
        const tag5 = Uint8Array.from([5]);    // envelope_pow (uvarint)
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp (uvarint)
        const tag100 = Uint8Array.from([100]); // sender (string)
        const tag101 = Uint8Array.from([101]); // target (string)
        const tag102 = Uint8Array.from([102]); // amount (uvarint)

        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            tag100, encStr(sender || ""),
            tag101, encStr(target || ""),
            tag102, uvarint64(amount || 0),  // Use 64-bit for large amounts (>4B umirage)
        );
    }

    /**
     * @param {number} proof
     * @param {Record<string, any>} transaction
     * @param {string} challenge
     * @param {string} privateKeyHex
     * @param {string} signerAddress
     * @param {(res: {success: boolean, error?: string, tx_hash?: string, result?: any}) => void} resolve
     */
    async handleTransactionResult(proof, transaction, challenge, privateKeyHex, signerAddress, resolve) {
        await ensureCosmCrypto();
        updateNotification("Preparing and broadcasting tx");

        // derive keys
        const privBytes = new Uint8Array(privateKeyHex.match(/.{1,2}/g).map((b) => parseInt(b, 16)));
        const pubBytes = secp256k1GetPublicKey(privBytes, true);
        // Use proper binary-to-base64 encoding
        const pubB64 = btoa(Array.from(pubBytes).map(b => String.fromCharCode(b)).join(''));

        let toRelay = { ...transaction, pubkey: pubB64, pow: proof, signature: "" };

        try {
            // Compute canonical bytes per Tx type and sign
            const action = transaction.action;
            let msgName = '';
            if (action === 'create_vote') msgName = 'MsgVote';
            else if (action === 'create_post' || action === 'create_comment') msgName = 'MsgPost';
            else if (action === 'follow_moderator') msgName = 'MsgFollowModerator';
            else if (action === 'unfollow_moderator') msgName = 'MsgUnfollowModerator';
            else if (action === 'follow_user') msgName = 'MsgFollowUser';
            else if (action === 'unfollow_user') msgName = 'MsgUnfollowUser';
            else if (action === 'follow_topic') msgName = 'MsgFollowTopic';
            else if (action === 'unfollow_topic') msgName = 'MsgUnfollowTopic';
            else if (action === 'block_post') msgName = 'MsgBlockPost';
            else if (action === 'unblock_post') msgName = 'MsgUnblockPost';
            else if (action === 'block_user') msgName = 'MsgBlockUser';
            else if (action === 'unblock_user') msgName = 'MsgUnblockUser';
            else if (action === 'block_topic') msgName = 'MsgBlockTopic';
            else if (action === 'unblock_topic') msgName = 'MsgUnblockTopic';
            else if (action === 'delete_post') msgName = 'MsgDelete';
            else if (action === 'send_tokens') msgName = 'MsgSendTokens';
            else if (action === 'set_username') msgName = 'MsgSetUsername';
            else if (action === 'report') msgName = 'MsgReport';
            else if (action === 'edit_post') msgName = 'MsgEdit';
            else if (action === 'upgrade_level') msgName = 'MsgUpgradeLevel';
            else if (action === 'set_auto_renewal') msgName = 'MsgSetAutoRenewal';
            else if (action === 'bridge_burn') msgName = 'MsgBridgeBurn';
            else throw new Error(`CRITICAL: Missing or invalid transaction.action: "${action}". Transaction must have explicit action field.`);

            let endpoint = '';
            if (msgName === 'MsgSetUsername') {
                // Sign relay for set username (must match chain ante)
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalSetUsername({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: signerAddress,
                    username: transaction.username || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                // Backend expects: pow, pow_difficulty, timestamp (envelope_timestamp)
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    username: transaction.username || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                // Include invite_code if present (for recruit quest completion)
                if (transaction.invite_code) {
                    toRelay.invite_code = transaction.invite_code;
                    console.log('[InviteCode] Added invite_code to set_username request:', transaction.invite_code);
                }
                // Include referrer if present (for referral system)
                try {
                    const referrer = localStorage.getItem('referrer_address');
                    console.log('[Referral] Reading from localStorage:', referrer);
                    if (referrer && referrer.startsWith('mirage1') && referrer.length >= 39) {
                        toRelay.referrer = referrer;
                        console.log('[Referral] Added referrer to set_username request:', referrer);
                    }
                } catch (e) { console.error('[Referral] Error reading referrer:', e); }
                endpoint = 'core/set_username';
            } else if (msgName === 'MsgSetModerators') {
                // Sign relay for set moderators (must match chain ante)
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalSetModerators({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: signerAddress,
                    moderators: transaction.moderators || [],
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    moderators: transaction.moderators || [],
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/set_moderators';
            } else if (msgName === 'MsgFollowModerator') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const modLower = (transaction.moderator || "").toLowerCase();
                const canon = this.canonicalFollowModerator({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    moderator: modLower,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    moderator: modLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/follow_moderator';
            } else if (msgName === 'MsgUnfollowModerator') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const modLower = (transaction.moderator || "").toLowerCase();
                const canon = this.canonicalUnfollowModerator({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    moderator: modLower,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    moderator: modLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/unfollow_moderator';
            } else if (msgName === 'MsgFollowUser') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const userLower = (transaction.user || "").toLowerCase();
                const canon = this.canonicalFollowUser({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    user: userLower,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    user: userLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/follow_user';
            } else if (msgName === 'MsgUnfollowUser') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const userLower = (transaction.user || "").toLowerCase();
                const canon = this.canonicalUnfollowUser({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    user: userLower,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    user: userLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/unfollow_user';
            } else if (msgName === 'MsgFollowTopic') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const topicLower = (transaction.topic || "").toLowerCase();
                const canon = this.canonicalFollowTopic({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    topic: topicLower,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    topic: topicLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/follow_topic';
            } else if (msgName === 'MsgUnfollowTopic') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const topicLower = (transaction.topic || "").toLowerCase();
                const canon = this.canonicalUnfollowTopic({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    topic: topicLower,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    topic: topicLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/unfollow_topic';
            } else if (msgName === 'MsgBlockPost') {
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalBlockPost({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/block_post';
            } else if (msgName === 'MsgUnblockPost') {
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalUnblockPost({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/unblock_post';
            } else if (msgName === 'MsgBlockUser') {
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalBlockUser({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/block_user';
            } else if (msgName === 'MsgUnblockUser') {
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalUnblockUser({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/unblock_user';
            } else if (msgName === 'MsgBlockTopic') {
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalBlockTopic({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    topic: transaction.topic || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    topic: transaction.topic || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/block_topic';
            } else if (msgName === 'MsgUnblockTopic') {
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalUnblockTopic({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    topic: transaction.topic || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    topic: transaction.topic || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/unblock_topic';
            } else if (msgName === 'MsgDelete') {
                // Sign relay for delete post (must match chain ante)
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalDelete({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/delete_post';
            } else if (msgName === 'MsgSendTokens') {
                // Sign relay for send tokens (must match chain ante)
                const difficulty = resolveTxDifficulty(transaction);
                // Ensure addresses are lowercase for consistency with backend
                const senderLower = (signerAddress || "").toLowerCase();
                const targetLower = (transaction.target || "").toLowerCase();
                const canonParams = {
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    sender: senderLower,
                    target: targetLower,
                    amount: Number(transaction.amount || 0),
                };
                const canon = this.canonicalSendTokens(canonParams);
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    amount: Number(transaction.amount || 0),
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/send_tokens';
            } else if (msgName === 'MsgReport') {
                const difficulty = resolveTxDifficulty(transaction);
                const uvarint = (n) => {
                    const out = [];
                    let v = (n >>> 0);
                    while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
                    out.push(v);
                    return Uint8Array.from(out);
                };
                const uvarint64 = (n) => {
                    const out = [];
                    let v = BigInt(n || 0);
                    while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
                    out.push(Number(v));
                    return Uint8Array.from(out);
                };
                const encStr = (s) => {
                    const b = new TextEncoder().encode(s || "");
                    return new Uint8Array([...uvarint(b.length), ...b]);
                };
                const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
                const hexToBytes = (hex) => {
                    const h = (hex || "").replace(/^0x/i, "");
                    if (!h || h.length % 2) return new Uint8Array(0);
                    const arr = new Uint8Array(h.length / 2);
                    for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
                    return arr;
                };
                const concat = (...arrs) => {
                    let total = 0; arrs.forEach(a => total += a.length);
                    const out = new Uint8Array(total);
                    let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
                    return out;
                };
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgReport\x00");
                const tag2 = Uint8Array.from([2]);    // envelope_pubkey
                const tag3 = Uint8Array.from([3]);    // envelope_block_hash
                const tag4 = Uint8Array.from([4]);    // envelope_difficulty
                const tag5 = Uint8Array.from([5]);    // envelope_pow
                const tag6 = Uint8Array.from([6]);    // envelope_timestamp
                const tag100 = Uint8Array.from([100]); // target
                const tag101 = Uint8Array.from([101]); // reason
                const canon = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag5, uvarint(Number(proof)),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(transaction.reason || ""),
                );
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    reason: transaction.reason || "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                };
                endpoint = 'core/report';
            } else if (msgName === 'MsgPost') {
                // Sign relay for post
                const topic = transaction.topic || "";
                const mediaArr = Array.isArray(transaction.media) ? transaction.media : [];
                const canon = this.canonicalPost({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: resolveTxDifficulty(transaction),
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    topic: topic,
                    title: transaction.title || "",
                    content: transaction.content || "",
                    tag: transaction.tag || "",
                    media: mediaArr,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    ...toRelay,
                    signature: sigB64,
                    topic: topic,
                    tag: transaction.tag || "",
                    media: mediaArr,
                };
                endpoint = 'core/post';
            } else if (msgName === 'MsgEdit') {
                // Sign relay for edit
                const topic = transaction.topic || "";
                const mediaArr = Array.isArray(transaction.media) ? transaction.media : [];
                const canon = this.canonicalEdit({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: resolveTxDifficulty(transaction),
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    topic: topic,
                    title: transaction.title || "",
                    content: transaction.content || "",
                    tag: transaction.tag || "",
                    override: String(transaction.override || '').toLowerCase(),
                    media: mediaArr,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    ...toRelay,
                    signature: sigB64,
                    topic: topic,
                    tag: transaction.tag || "",
                    media: mediaArr,
                };
                endpoint = 'core/edit';
            } else if (msgName === 'MsgVote') {
                // Sign relay for vote (must match chain ante_metasig)
                const uvarint = (n) => {
                    const out = [];
                    let v = (n >>> 0);
                    while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
                    out.push(v);
                    return Uint8Array.from(out);
                };
                const uvarint64 = (n) => {
                    const out = [];
                    let v = BigInt(n || 0);
                    while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
                    out.push(Number(v));
                    return Uint8Array.from(out);
                };
                const encStr = (s) => {
                    const b = new TextEncoder().encode(s);
                    return new Uint8Array([...uvarint(b.length), ...b]);
                };
                const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
                const hexToBytes = (hex) => {
                    const h = (hex || "").replace(/^0x/i, "");
                    if (!h || h.length % 2) return new Uint8Array(0);
                    const arr = new Uint8Array(h.length / 2);
                    for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
                    return arr;
                };
                const concat = (...arrs) => {
                    let total = 0; arrs.forEach(a => total += a.length);
                    const out = new Uint8Array(total);
                    let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
                    return out;
                };
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgVote\x00");
                const tag2 = Uint8Array.from([2]);   // envelope_pubkey
                const tag3 = Uint8Array.from([3]);   // envelope_block_hash
                const tag4 = Uint8Array.from([4]);   // envelope_difficulty
                const tag5 = Uint8Array.from([5]);   // envelope_pow
                const tag6 = Uint8Array.from([6]);   // envelope_timestamp
                const tag100 = Uint8Array.from([100]); // target
                const tag101 = Uint8Array.from([101]); // direction
                // Direction is int32 in proto, but Go/backend converts to uint32 before encoding
                // In JS, use >>> 0 to get unsigned (& 0xFFFFFFFF doesn't work for negative numbers in JS)
                const signDirUnsigned = Number(transaction.direction) >= 0
                    ? Number(transaction.direction)
                    : (Number(transaction.direction) >>> 0);
                const voteSignData = {
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: resolveTxDifficulty(transaction),
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    direction: signDirUnsigned,
                };
                // Canonical order per Go ante_metasig.go: 2,3,4,5,6,100,101
                const canon = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(voteSignData.last_block_hash)),
                    tag4, uvarint(voteSignData.pow_difficulty),
                    tag5, uvarint(voteSignData.proof),
                    tag6, uvarint64(voteSignData.timestamp || 0),
                    tag100, encStr(voteSignData.target),
                    tag101, uvarint(voteSignData.direction),
                );
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                // Only send fields the backend actually reads — omit noise like
                // pow_base_bits, pow_factor, difficulty, action.
                // NOTE: direction must be the original signed value (-1/0/1), NOT
                // signDirUnsigned which is the unsigned encoding for canonical signing.
                toRelay = {
                    pubkey: toRelay.pubkey,
                    signature: sigB64,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: resolveTxDifficulty(transaction),
                    pow: Number(proof),
                    target: transaction.target || "",
                    direction: Number(transaction.direction),
                    timestamp: transaction.timestamp,
                };
                endpoint = 'core/vote';
            } else if (msgName === 'MsgUpgradeLevel') {
                // Sign relay for upgrade level (must match chain ante_metasig)
                // Note: PoW is NOT allowed for MsgUpgradeLevel - must pay with tokens
                const uvarint = (n) => {
                    const out = [];
                    let v = (n >>> 0);
                    while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
                    out.push(v);
                    return Uint8Array.from(out);
                };
                const uvarint64 = (n) => {
                    const out = [];
                    let v = BigInt(n || 0);
                    while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
                    out.push(Number(v));
                    return Uint8Array.from(out);
                };
                const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
                const hexToBytes = (hex) => {
                    const h = (hex || "").replace(/^0x/i, "");
                    if (!h || h.length % 2) return new Uint8Array(0);
                    const arr = new Uint8Array(h.length / 2);
                    for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
                    return arr;
                };
                const concat = (...arrs) => {
                    let total = 0; arrs.forEach(a => total += a.length);
                    const out = new Uint8Array(total);
                    let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
                    return out;
                };
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUpgradeLevel\x00");
                const tag2 = Uint8Array.from([2]);   // envelope_pubkey
                const tag3 = Uint8Array.from([3]);   // envelope_block_hash
                const tag4 = Uint8Array.from([4]);   // envelope_difficulty (always 0)
                const tag5 = Uint8Array.from([5]);   // envelope_pow (always 0 for upgrade)
                const tag6 = Uint8Array.from([6]);   // envelope_timestamp
                const tag100 = Uint8Array.from([100]); // level
                const targetLevel = Number(transaction.level || 0);
                const canon = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(0), // difficulty always 0 for upgrade
                    tag5, uvarint(0), // pow always 0 for upgrade
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, uvarint(targetLevel),
                );
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp || 0,
                    last_block_hash: transaction.last_block_hash,
                    level: targetLevel,
                };
                endpoint = 'core/upgrade_level';
            } else if (msgName === 'MsgSetAutoRenewal') {
                // Sign relay for set_auto_renewal (must match chain ante_metasig)
                // Note: PoW is NOT allowed for MsgSetAutoRenewal - must pay via reserve
                const uvarint = (n) => {
                    const out = [];
                    let v = (n >>> 0);
                    while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
                    out.push(v);
                    return Uint8Array.from(out);
                };
                const uvarint64 = (n) => {
                    const out = [];
                    let v = BigInt(n || 0);
                    while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
                    out.push(Number(v));
                    return Uint8Array.from(out);
                };
                const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
                const hexToBytes = (hex) => {
                    const h = (hex || "").replace(/^0x/i, "");
                    if (!h || h.length % 2) return new Uint8Array(0);
                    const arr = new Uint8Array(h.length / 2);
                    for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
                    return arr;
                };
                const concat = (...arrs) => {
                    let total = 0; arrs.forEach(a => total += a.length);
                    const out = new Uint8Array(total);
                    let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
                    return out;
                };
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetAutoRenewal\x00");
                const tag2 = Uint8Array.from([2]);   // envelope_pubkey
                const tag3 = Uint8Array.from([3]);   // envelope_block_hash
                const tag4 = Uint8Array.from([4]);   // envelope_difficulty (always 0)
                const tag5 = Uint8Array.from([5]);   // envelope_pow (always 0)
                const tag6 = Uint8Array.from([6]);   // envelope_timestamp
                const tag100 = Uint8Array.from([100]); // auto_renew (0 or 1)
                const flag = Boolean(transaction.auto_renew);
                const canon = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(0),
                    tag5, uvarint(0),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, uvarint(flag ? 1 : 0),
                );
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp || 0,
                    last_block_hash: transaction.last_block_hash,
                    auto_renew: flag,
                };
                endpoint = 'core/set_auto_renewal';
            } else if (msgName === 'MsgBridgeBurn') {
                // Sign relay for bridge burn (e.g., Solana)
                const difficulty = resolveTxDifficulty(transaction);
                const uvarint = (n) => {
                    const out = [];
                    let v = (n >>> 0);
                    while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
                    out.push(v);
                    return Uint8Array.from(out);
                };
                const uvarint64 = (n) => {
                    const out = [];
                    let v = BigInt(n || 0);
                    while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
                    out.push(Number(v));
                    return Uint8Array.from(out);
                };
                const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
                const encStr = (s) => { const b = new TextEncoder().encode(s || ""); return new Uint8Array([...uvarint(b.length), ...b]); };
                const hexToBytes = (hex) => {
                    const h = (hex || "").replace(/^0x/i, "");
                    if (!h || h.length % 2) return new Uint8Array(0);
                    const arr = new Uint8Array(h.length / 2);
                    for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
                    return arr;
                };
                const concat = (...arrs) => {
                    let total = 0; arrs.forEach(a => total += a.length);
                    const out = new Uint8Array(total);
                    let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
                    return out;
                };
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgBridgeBurn\x00");
                const tag2 = Uint8Array.from([2]);   // envelope_pubkey
                const tag3 = Uint8Array.from([3]);   // envelope_block_hash
                const tag4 = Uint8Array.from([4]);   // envelope_difficulty
                const tag5 = Uint8Array.from([5]);   // envelope_pow
                const tag6 = Uint8Array.from([6]);   // envelope_timestamp
                const tag100 = Uint8Array.from([100]); // destination_chain
                const tag101 = Uint8Array.from([101]); // destination_address
                const tag102 = Uint8Array.from([102]); // amount
                const canon = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag5, uvarint(Number(proof)),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.destination_chain || ""),
                    tag101, encStr(transaction.destination_address || ""),
                    tag102, uvarint64(transaction.amount || 0),
                );
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp || 0,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    destination_chain: transaction.destination_chain || "",
                    destination_address: transaction.destination_address || "",
                    amount: transaction.amount || 0,
                };
                endpoint = 'bridge/burn';
            }

            // Submit transaction
            try {
                const out = await Api.post(endpoint, toRelay);
                // Reports return {success: true, id: ...} instead of {tx_hash: ...}
                const txHash = (out && out.tx_hash) ? String(out.tx_hash).toLowerCase() :
                    ((endpoint === 'core/report' && out && out.success && out.id) ? `report-${out.id}` : null);
                if (txHash || (endpoint === 'core/report' && out && out.success)) {
                    // If we reserved a fee for this submission, leave it pending until next status update reduces it
                    // No change here; pending is adjusted via status fetch above

                    // For votes, update local direction and vote count only after tx is successfully sent
                    if (endpoint === 'core/vote' && transaction && transaction.action === 'create_vote') {
                        try {
                            const targetIdRaw = String(transaction.target || '').trim();
                            if (targetIdRaw && this.getPost && this.updatePost) {
                                // Use the same key casing that the app state uses for posts
                                // Try exact key first; if missing, fall back to lowercase
                                let post = this.getPost(targetIdRaw);
                                let targetId = targetIdRaw;
                                if (!post) {
                                    const lower = targetIdRaw.toLowerCase();
                                    if (lower && lower !== targetIdRaw) {
                                        post = this.getPost(lower);
                                        if (post) targetId = lower;
                                    }
                                }
                                if (post) {
                                    const prevDir = (typeof post.direction === 'number') ? post.direction : 0;
                                    const newDir = Number(transaction.direction) || 0;
                                    const prevPoints = (typeof post.points === 'number')
                                        ? post.points
                                        : (Number(post.points) || 0);
                                    const nextPoints = prevPoints + (newDir - prevDir);
                                    this.updatePost(targetId, { direction: newDir, points: nextPoints });
                                }
                            }
                            // Persist own vote highlight so arrows reflect immediately on future loads
                            try {
                                Storage.setVote(String(transaction.target || '').trim(), Number(transaction.direction) || 0, 100);
                            } catch (_) { }
                        } catch (_) { }
                    }

                    try {
                        // NOTE: We no longer inject transient posts or comments into the UI here.
                        // Posts and comments must only appear after they are confirmed on-chain
                        // and fetched back from the backend. Root posts are shown via CreatePostView
                        // redirect + fetch, and replies via ViewPostView reloading comments.

                        // For comments, we still update the root post's last-visit comment count
                        // and timestamp so frontpage "+X new" indicators behave correctly, but we
                        // do NOT add a temporary comment object to the parent's children.
                        try {
                            const parentId = String(transaction.target || '').trim();
                            if (parentId && transaction.action === 'create_comment' && this.getPost) {
                                const parent = this.getPost(parentId);
                                if (parent) {
                                    // Update root post's last-visit comment count immediately so frontpage won't show "+1 new" for own comment
                                    // Also update last-visit timestamp to "now + 10s" to suppress highlight
                                    const performVisitUpdate = async () => {
                                        try {
                                            let rootId = parentId;
                                            // If parent is a comment (no title), we need to find the real root.
                                            // Since the new comment (txHash) might not be indexed yet, we resolve the root using the PARENT ID.
                                            // The parent ID is already on chain and indexed.
                                            if (!parent || !(parent.title && String(parent.title).trim() !== '')) {
                                                try {
                                                    // Ask backend for the root of the PARENT, which is stable
                                                    const res = await Api.get('get_root_post_id', { comment_id: parentId });
                                                    if (res && res.root_post_id) {
                                                        rootId = String(res.root_post_id).toLowerCase();
                                                    }
                                                } catch (err) {
                                                    // Last resort fallback: try the new comment hash (might fail if race condition)
                                                    if (txHash) {
                                                        try {
                                                            const res2 = await Api.get('get_root_post_id', { comment_id: txHash }, { timeoutMs: 5000 });
                                                            if (res2 && res2.root_post_id) {
                                                                rootId = String(res2.root_post_id).toLowerCase();
                                                            }
                                                        } catch (_) { }
                                                    }
                                                }
                                            }

                                            if (!rootId) {
                                                return;
                                            }

                                            // Increment visit count
                                            const prev = Storage.getLastVisitCommentCount(rootId);

                                            if (prev !== null && prev !== undefined) {
                                                const newVal = Number(prev) + 1;
                                                Storage.setLastVisitCommentCount(rootId, newVal);
                                            } else {
                                                // If no previous count, try to fetch current count from API for the ROOT post
                                                // We can't rely on 'parent.comments' if parent is a comment, because that's the reply count of the comment, not the root.
                                                try {
                                                    // If we have the root post object in state, use it
                                                    let currentRootCount = 0;
                                                    const rootPost = this.getPost ? this.getPost(rootId) : null;
                                                    if (rootPost && typeof rootPost.comments === 'number') {
                                                        currentRootCount = rootPost.comments;
                                                    } else {
                                                        // Fetch root post to get accurate current count
                                                        const p = await Api.get('get_post', { post_id: rootId }, { timeoutMs: 5000 });
                                                        if (p && typeof p.comments === 'number') {
                                                            currentRootCount = p.comments;
                                                        }
                                                    }
                                                    // Set it to current + 1 (assuming our new comment isn't included in that count yet, OR set to count if it is?)
                                                    // If we fetched from API, and API is fast, it might include our comment.
                                                    // But safer to just ensure it's at least what we saw + 1.
                                                    // Actually, simpler heuristic: if we just added a comment, we want to suppress "new".
                                                    // Setting timestamp is the most important part for "new" highlight.
                                                    // Setting count is for the "(+X new)" text.
                                                    // Let's just set it to currentRootCount + 1.
                                                    const newVal = currentRootCount + 1;
                                                    Storage.setLastVisitCommentCount(rootId, newVal);
                                                } catch (e) { }
                                            }

                                            // Update timestamp to suppress highlight (now + 10s buffer)
                                            const nowSec = Math.floor(Date.now() / 1000);
                                            Storage.setLastVisitTimestamp(rootId, nowSec + 10);

                                        } catch (err) { }
                                    };
                                    // Execute immediately without delay
                                    performVisitUpdate();
                                }
                            }
                        } catch (_) { }

                        // If this was an edit, update the edited post locally
                        try {
                            if (transaction.action === 'edit_post' && this.updatePost) {
                                const nowTs = Math.floor(Date.now() / 1000);
                                const overrideId = String(transaction.override || '').toLowerCase();
                                const isRoot = (typeof transaction.title === 'string' && transaction.title.trim().length > 0) || !transaction.target;
                                const patch = {
                                    edited: true,
                                    edited_ts: nowTs,
                                    content: transaction.content || '',
                                    flash: true,
                                };
                                if (isRoot) {
                                    patch.title = transaction.title || '';
                                    patch.topic = transaction.topic || '';
                                }
                                if (Array.isArray(transaction.media)) {
                                    patch.media = transaction.media;
                                }
                                this.updatePost(overrideId, patch);
                                // Clear flash after animation delay
                                setTimeout(() => {
                                    try {
                                        if (this.updatePost) {
                                            this.updatePost(overrideId, { flash: false });
                                        }
                                    } catch (_) { }
                                }, 1250);
                            }
                        } catch (_) { }

                        // Ensure the new topic is available immediately in the topics list
                        try {
                            const t = (transaction && typeof transaction.topic === 'string') ? transaction.topic.trim() : '';
                            if (t) {
                                const stored = Storage.load('topics', { topics: [], lastSorted: null }) || {};
                                const existing = Array.isArray(stored.topics) ? stored.topics : [];
                                const set = new Set(existing.filter((x) => typeof x === 'string' && x));
                                set.add('all');
                                set.add(t);
                                const nextTopics = ['all', ...Array.from(set).filter((x) => x !== 'all')];
                                Storage.save('topics', { topics: nextTopics, lastSorted: new Date() });
                            }
                        } catch (_) { }
                        // No-op: vote highlight is keyed by post_id and is handled by VoteSection + create_vote handler.
                    } catch (_) { }
                }
                // For reports, success is determined by the response.success field
                const success = (endpoint === 'core/report') ? (out && out.success === true) : !!txHash;
                if (success) {
                    updateNotification("Transaction submitted");

                    // For votes, poll for indexed details to show weight
                    if (endpoint === 'core/vote' && txHash) {
                        const target = (transaction && transaction.action === 'create_vote') ? transaction.target : null;
                        this._startVoteDetailsPoll(txHash, target);
                    }

                    // Dispatch event for quest-relevant actions so quest progress can refresh
                    const action = transaction?.action;
                    if (action === 'create_vote' || action === 'create_post' || action === 'create_comment') {
                        console.log('[TransactionHandler] Dispatching questActionCompleted for action:', action);
                        window.dispatchEvent(new CustomEvent('questActionCompleted', { detail: { action, txHash } }));
                    }
                } else {
                    // API returned an error in the response body (not an exception)
                    const errMsg = out?.error || out?.message || 'Transaction failed';
                    updateNotification(errMsg, 5, true);
                }
                resolve({ success: success, tx_hash: txHash, result: out, error: out?.error });
                return;
            } catch (e) {
                // Convert entire error to string for checking
                const whole = String(e && e.message ? e.message : e);
                // Check for subscription/reserve errors in the full error string
                if (/insufficient reserve/i.test(whole) || /subscription terminated/i.test(whole)) {
                    // Don't show notification here - let outer catch handle it to avoid duplicates
                } else if (/admin insufficient balance/i.test(whole)) {
                    updateNotification('Your account balance is too low to cover the transaction fee. Please fund your account.', 8, true);
                } else if (/insufficient funds/i.test(whole)) {
                    updateNotification('Unfortunately the node does not have enough gas available to complete this transaction.', 6, true);
                }
                throw e;
            }
        } catch (error) {
            console.error('Transaction error:', error);
            // Convert entire error to string for checking - check both message and stringified error
            const errMsg = String(error && error.message ? error.message : error);
            const errStr = String(error);
            const fullErr = errMsg + ' ' + errStr;
            // Check for subscription/reserve errors in the full error string
            if (/insufficient reserve/i.test(fullErr) || /subscription terminated/i.test(fullErr)) {
                // Extract the actual error message from gRPC wrapper for cleaner display
                const grpcMatch = fullErr.match(/details\s*=\s*"([^"]+)"/);
                const cleanMsg = grpcMatch && grpcMatch[1] ? grpcMatch[1] : 'Your subscription reserve is empty. Please top up your reserve funds or use PoW (free tier).';
                updateNotification(cleanMsg, 10, true);
            } else if (/pow_required/i.test(fullErr)) {
                // Backend detected we're not a subscriber but frontend thought we were
                // Clear cached subscription status to force re-fetch
                console.warn('Subscription status mismatch detected - clearing cached user_level');
                try {
                    Storage.save('user_level', '0');
                    window.dispatchEvent(new CustomEvent('subscriptionStatusChanged', { detail: { level: 0 } }));
                } catch (_) { }
                updateNotification('Your subscription may have expired. Please try again - PoW will be used.', 8, true);
            } else if (/admin insufficient balance/i.test(fullErr)) {
                updateNotification('Your account balance is too low to cover the transaction fee. Please fund your account.', 8, true);
            } else if (/insufficient funds/i.test(fullErr)) {
                updateNotification('Node does not have enough gas for this transaction.', 6, true);
            } else {
                // Show a cleaner error message - extract key info if possible
                let cleanMsg = errMsg;
                // Try to extract the actual error from gRPC wrapper
                const grpcMatch = fullErr.match(/details\s*=\s*"([^"]+)"/);
                if (grpcMatch && grpcMatch[1]) {
                    cleanMsg = grpcMatch[1];
                }
                updateNotification(cleanMsg || "Transaction failed", 5, true);
            }
            resolve({
                success: false,
                error: error.message
            });
        }
    }

    /**
     * @param {Record<string, any>} transaction
     * @param {string} challenge
     * @param {string} privateKeyHex
     * @param {string} signerAddress
     * @param {boolean=} forcePow
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    performTransaction(transaction, challenge, privateKeyHex, signerAddress, forcePow = false) {
        return new Promise((resolve) => {
            const wrapResolve = (result) => {
                resolve(result);
            };

            // Set timestamp for replay protection if not already set
            if (!transaction.timestamp) {
                transaction.timestamp = Date.now();
            }

            // Subscribers (level >= 1) skip PoW — chain trusts them.
            // Fee-only actions (upgrade_level, set_auto_renewal) never use PoW regardless of level.
            // NOTE: pow_difficulty=0 for a free user means "base difficulty" (0 extra steps),
            // which still requires computing a valid argon2 hash.  Do NOT skip PoW for that.
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            const NO_POW_ACTIONS = new Set(['upgrade_level', 'set_auto_renewal']);
            const canSkipPow = !forcePow && (userLevel >= 1 || NO_POW_ACTIONS.has(transaction.action));

            // Inform UI that we are starting a transaction
            this._setStatus("preparing");

            if (canSkipPow) {
                // Skip PoW computation - subscribers must NOT use PoW (difficulty and proof must be 0)
                if (transaction && typeof transaction === "object") {
                    transaction.pow_difficulty = 0;
                    transaction.difficulty = 0;
                    transaction.pow = 0;
                }
                updateNotification("Submitting transaction");
                (async () => {
                    this._setStatus("submitting");
                    try {
                        await this.handleTransactionResult(0, transaction, challenge, privateKeyHex, signerAddress, wrapResolve);
                    } finally {
                        this._setStatus("idle");
                    }
                })();
                return;
            }
            // Perform PoW as usual
            const worker = new Worker("/pow/worker.js");

            // Set the flag before starting PoW
            if (this.setWarnOnLeave) {
                this.setWarnOnLeave(true);
            }
            // Keep status as "preparing" during PoW; UI only sees "preparing" -> "submitting"

            // Build canonical base bytes for MsgPost/MsgVote/MsgSetUsername (no pow), matching chain ante
            const bytesToHex = (buf) => Array.from(buf).map((b) => b.toString(16).padStart(2, '0')).join('');
            const uvarint = (n) => {
                const out = [];
                let v = (n >>> 0);
                while (v >= 0x80) { out.push(((v & 0x7f) | 0x80)); v >>>= 7; }
                out.push(v);
                return Uint8Array.from(out);
            };
            const encStr = (s) => {
                const b = new TextEncoder().encode(s || "");
                return new Uint8Array([...uvarint(b.length), ...b]);
            };
            const encBytes = (arr) => new Uint8Array([...uvarint(arr.length), ...arr]);
            const hexToBytes = (hex) => {
                const h = (hex || "").replace(/^0x/i, "");
                if (!h || h.length % 2) return new Uint8Array(0);
                const arr = new Uint8Array(h.length / 2);
                for (let i = 0; i < arr.length; i++) arr[i] = parseInt(h.substr(i * 2, 2), 16);
                return arr;
            };
            const concat = (...arrs) => {
                let total = 0; arrs.forEach(a => total += a.length);
                const out = new Uint8Array(total);
                let off = 0; for (const a of arrs) { out.set(a, off); off += a.length; }
                return out;
            };
            const privBytes = new Uint8Array(privateKeyHex.match(/.{1,2}/g).map((b) => parseInt(b, 16)));
            const pubBytes = secp256k1GetPublicKey(privBytes, true);
            const difficulty = requirePowDifficulty(
                typeof transaction.pow_difficulty !== 'undefined' ? transaction.pow_difficulty : transaction.difficulty
            );
            const powBaseBits = requirePowBaseBits(transaction.pow_base_bits);
            const powFactor = requirePowFactor(transaction.pow_factor);

            let baseBytes;
            const action = transaction.action;

            // Helper for 64-bit uvarint (for timestamps)
            const uvarint64 = (n) => {
                const out = [];
                let v = BigInt(n || 0);
                while (v >= 0x80n) { out.push(Number((v & 0x7fn) | 0x80n)); v >>= 7n; }
                out.push(Number(v));
                return Uint8Array.from(out);
            };
            const tag6 = Uint8Array.from([6]);   // envelope_timestamp

            if (action === 'create_vote') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgVote\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                // Direction is int32 in proto, but Go/backend converts to uint32 before encoding
                // In JS, use >>> 0 to get unsigned (& 0xFFFFFFFF doesn't work for negative numbers in JS)
                const dirUnsigned = Number(transaction.direction) >= 0
                    ? Number(transaction.direction)
                    : (Number(transaction.direction) >>> 0);
                const powData = {
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    direction: dirUnsigned,
                };
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(powData.last_block_hash)),
                    tag4, uvarint(powData.difficulty),
                    tag6, uvarint64(powData.timestamp || 0),
                    tag100, encStr(powData.target),
                    tag101, uvarint(powData.direction),
                );
            } else if (action === 'create_post' || action === 'create_comment') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgPost\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]); // topic
                const tag102 = Uint8Array.from([102]);
                const tag103 = Uint8Array.from([103]);
                const tag104 = Uint8Array.from([104]); // tag
                const tag105 = Uint8Array.from([105]); // media (v1.12.0)
                const topic = transaction.topic || "";
                const mediaParts = [];
                for (const m of (transaction.media || [])) {
                    mediaParts.push(tag105);
                    mediaParts.push(encStr(m));
                }
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(topic),
                    tag102, encStr(transaction.title || ""),
                    tag103, encStr(transaction.content || ""),
                    tag104, encStr(transaction.tag || ""),
                    ...mediaParts,
                );
            } else if (action === 'set_moderators') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetModerators\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);

                // Build repeated moderators field
                const modsParts = [];
                for (const mod of (transaction.moderators || [])) {
                    modsParts.push(tag101);
                    modsParts.push(encStr(mod));
                }

                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(signerAddress),
                    ...modsParts,
                );
            } else if (action === 'follow_moderator' || action === 'unfollow_moderator') {
                const prefix = new TextEncoder().encode(
                    action === 'follow_moderator'
                        ? "mirage.core.v1:MsgFollowModerator\x00"
                        : "mirage.core.v1:MsgUnfollowModerator\x00"
                );
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(signerAddress.toLowerCase()),
                    tag101, encStr((transaction.moderator || "").toLowerCase()),
                );
            } else if (action === 'set_username') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetUsername\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(signerAddress),
                    tag101, encStr(transaction.username || ""),
                );
            } else if (action === 'follow_user') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgFollowUser\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(signerAddress.toLowerCase()),
                    tag101, encStr((transaction.user || "").toLowerCase()),
                );
            } else if (action === 'unfollow_user') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnfollowUser\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(signerAddress.toLowerCase()),
                    tag101, encStr((transaction.user || "").toLowerCase()),
                );
            } else if (action === 'follow_topic') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgFollowTopic\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(signerAddress.toLowerCase()),
                    tag101, encStr((transaction.topic || "").toLowerCase()),
                );
            } else if (action === 'unfollow_topic') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnfollowTopic\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(signerAddress.toLowerCase()),
                    tag101, encStr((transaction.topic || "").toLowerCase()),
                );
            } else if (action === 'block_post') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockPost\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                );
            } else if (action === 'unblock_post') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockPost\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                );
            } else if (action === 'block_user') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockUser\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                );
            } else if (action === 'unblock_user') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockUser\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                );
            } else if (action === 'block_topic') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockTopic\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(transaction.topic || ""),
                );
            } else if (action === 'unblock_topic') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockTopic\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(transaction.topic || ""),
                );
            } else if (action === 'delete_post') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgDelete\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                );
            } else if (action === 'send_tokens') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgSendTokens\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                const tag102 = Uint8Array.from([102]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.sender || signerAddress),
                    tag101, encStr(transaction.target || ""),
                    tag102, uvarint64(transaction.amount || 0),  // Use 64-bit for large amounts
                );
            } else if (action === 'report') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgReport\x00");
                const tag2 = Uint8Array.from([2]);    // envelope_pubkey
                const tag3 = Uint8Array.from([3]);    // envelope_block_hash
                const tag4 = Uint8Array.from([4]);    // envelope_difficulty
                // envelope_pow (tag 5) is NOT included in base - it's appended during PoW validation
                const tag6 = Uint8Array.from([6]);   // envelope_timestamp
                const tag100 = Uint8Array.from([100]); // target
                const tag101 = Uint8Array.from([101]); // reason
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(transaction.reason || ""),
                );
            } else if (action === 'edit_post') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgEdit\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag6 = Uint8Array.from([6]);   // envelope_timestamp
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]); // topic
                const tag102 = Uint8Array.from([102]);
                const tag103 = Uint8Array.from([103]);
                const tag104 = Uint8Array.from([104]); // tag
                const tag105 = Uint8Array.from([105]); // override
                const tag106 = Uint8Array.from([106]); // media
                const topic = transaction.topic || "";
                const mediaParts = [];
                for (const m of (transaction.media || [])) {
                    mediaParts.push(tag106);
                    mediaParts.push(encStr(m));
                }
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(topic),
                    tag102, encStr(transaction.title || ""),
                    tag103, encStr(transaction.content || ""),
                    tag104, encStr(transaction.tag || ""),
                    tag105, encStr(String(transaction.override || "").toLowerCase()),
                    ...mediaParts,
                );
            } else if (action === 'upgrade_level') {
                // upgrade_level should NEVER use PoW - it must be paid with tokens
                // This branch should not be reached, but handle gracefully
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUpgradeLevel\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag5 = Uint8Array.from([5]);
                const tag100 = Uint8Array.from([100]);
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(0), // difficulty always 0
                    tag5, uvarint(0),
                    tag100, uvarint(Number(transaction.level) || 0),
                );
            } else {
                throw new Error(`Unknown transaction action: "${action}". Must be one of: create_vote, create_post, create_comment, set_moderators, set_username, follow_user, unfollow_user, follow_topic, unfollow_topic, block_post, unblock_post, block_user, unblock_user, block_topic, unblock_topic, delete_post, send_tokens, report, edit_post, upgrade_level, set_auto_renewal`);
            }
            const baseHex = bytesToHex(baseBytes);
            const saltHex = String(transaction.last_block_hash || '').toLowerCase();
            // Use a random starting nonce so repeated clicks in the same block
            // produce different valid PoW solutions (and thus different tx hashes).
            const start = Math.floor(Math.random() * 0xffffffff) >>> 0;
            worker.postMessage({ baseHex, difficulty, powBaseBits, powFactor, saltHex, start });

            let taken = 0;
            let powTimedOut = false;

            const intervalId = setInterval(() => {
                taken += 0.1;
                if (this.totalTransactions === 0)
                    updateNotification(`Performing PoW for single tx (${taken.toFixed(1)} secs)`);
                else
                    updateNotification(`Performing PoW for tx ${this.processedTransactions}/${this.totalTransactions} (${taken.toFixed(1)} secs)`);
            }, 100); // Update every second

            // 60-second timeout for PoW
            const powTimeoutId = setTimeout(() => {
                if (powTimedOut) return;
                powTimedOut = true;
                worker.terminate();
                clearInterval(intervalId);
                if (this.setWarnOnLeave) {
                    this.setWarnOnLeave(false);
                }
                this._setStatus("idle");
                updateNotification("PoW took too long. Please try again.", 5.0, true);
                wrapResolve({ success: false, error: "Proof of work took too long (>60s). Your device may be too slow, or the network difficulty is too high. Please try again later." });
            }, 60000);

            worker.onmessage = async function (e) {
                if (powTimedOut) return;
                clearTimeout(powTimeoutId);

                // Received PoW result from the worker
                worker.terminate();

                // Clear the flag after PoW is done
                if (this.setWarnOnLeave) {
                    this.setWarnOnLeave(false);
                }

                // Stop the interval for updating notifications
                clearInterval(intervalId);

                updateNotification("Preparing and broadcasting tx");

                const workerData = e ? e.data : null;
                if (workerData && typeof workerData === 'object' && workerData.error) {
                    try { console.error('[PoW] worker error', workerData); } catch (_) { }
                    updateNotification("PoW failed. Please try again.", 5.0, true);
                    wrapResolve({ success: false, error: `Proof of work failed: ${workerData.error}` });
                    return;
                }
                if (typeof workerData !== 'number' || !Number.isFinite(workerData)) {
                    try { console.error('[PoW] invalid worker response', workerData); } catch (_) { }
                    updateNotification("PoW failed. Please try again.", 5.0, true);
                    wrapResolve({ success: false, error: "Proof of work failed: invalid worker response." });
                    return;
                }

                // IMPORTANT: PoW worker uses uint32 varint encoding (>>> 0). If the random start nonce is
                // near 0xffffffff, the worker can increment past 2^32 and still validate using uint32 wrap.
                // We MUST normalize to uint32 here so:
                // - the signature canonical bytes match backend verification
                // - the backend PoW digest uses the same uvarint(proof) encoding as the worker
                const rawProof = Number(workerData);
                const proof = rawProof >>> 0;

                // Log PoW completion stats
                const iterations = ((rawProof - start) >>> 0) + 1;
                const hashesPerSec = taken > 0.05 ? (iterations / taken).toFixed(1) : null;
                console.log(`[PoW] completed: ${taken.toFixed(2)}s, difficulty=${difficulty}, iterations=${iterations}, speed=${hashesPerSec || 'instant'} H/s`);
                if (rawProof !== proof) {
                    try {
                        console.warn('[PoW] proof overflow normalized', { rawProof, proof, start });
                    } catch (_) { }
                }
                this._setStatus("submitting");
                try {
                    await this.handleTransactionResult(proof, transaction, challenge, privateKeyHex, signerAddress, wrapResolve);
                    updateNotification(hashesPerSec ? `Transaction submitted (${hashesPerSec} H/s)` : "Transaction submitted");
                } finally {
                    this._setStatus("idle");
                }
                return;
            }.bind(this); // Bind 'this' to access the class instance
        });
    }

}

// Ensure singleton instance
const instance = new TransactionHandler();
export default instance;
