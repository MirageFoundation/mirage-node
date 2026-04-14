/* global BigInt */
import { updateNotification } from "../utils/notifications.js";
import Storage from './Storage';
import seedVault from './SeedVault';
import { getPublicKey as secp256k1GetPublicKey } from '@noble/secp256k1';
import { derivePrivateKeyFromSeed, derivePublicKeyFromSeed } from './CryptoUtils.js';
import Api from './api';
import { notifyTopicsUpdated, invalidateCache as invalidateSubCache } from './Subscriptions';
import { generateEnvelopeNonce } from './canonicalEncoding';
import { ensureCosmCrypto as ensureCosmCryptoShared } from './cosmCrypto';

const ALLOWED_TAGS = new Set(["", "sensitive", "adult", "gore", "violence", "death"]);

const LOCAL_ERROR_CODE_BY_MESSAGE = {
    "empty username": "username_required",
    "empty txhash": "tx_hash_required",
    "post is already blocked": "post_already_blocked",
    "block post already in progress": "block_post_in_progress",
    "unblock post already in progress": "unblock_post_in_progress",
    "empty address": "address_required",
    "empty user address": "address_required",
    "user is already blocked": "user_already_blocked",
    "block user already in progress": "block_user_in_progress",
    "unblock user already in progress": "unblock_user_in_progress",
    "empty topic": "topic_required",
    "topic is already blocked": "topic_already_blocked",
    "block topic already in progress": "block_topic_in_progress",
    "unblock topic already in progress": "unblock_topic_in_progress",
    "Not logged in": "not_logged_in",
    "follow user already in progress": "follow_user_in_progress",
    "unfollow user already in progress": "unfollow_user_in_progress",
    "follow topic already in progress": "follow_topic_in_progress",
    "unfollow topic already in progress": "unfollow_topic_in_progress",
    "empty agent address": "agent_address_required",
    "enable agent already in progress": "enable_agent_in_progress",
    "disable agent already in progress": "disable_agent_in_progress",
    "agents must be an array": "agents_must_be_array",
    "empty target": "target_required",
    "empty reason": "reason_required",
    "Invalid recipient or amount": "invalid_recipient_or_amount",
    "Recipient must be a mirage1 address": "recipient_must_be_mirage1",
    "Minimum amount is 0.001 MIRAGE": "amount_too_small",
    "Missing target or award type": "award_missing_target_or_type",
    "Invalid level (must be 1 or 10)": "invalid_level",
    "destination_chain required": "destination_chain_required",
    "destination_address required": "destination_address_required",
    "amount must be positive": "amount_must_be_positive",
    "missing recovery phrase": "missing_recovery_phrase",
    "invalid signer address": "invalid_signer_address",
    "invalid address": "address_invalid",
    "delete account already in progress": "delete_in_progress",
    "invalid override": "invalid_override",
    "invalid tag": "invalid_tag",
    "Vote already pending": "vote_already_pending",
    "Proof of work took too long (>60s). Your device may be too slow, or the network difficulty is too high. Please try again later.": "pow_timeout",
    "Proof of work failed: invalid worker response.": "pow_worker_invalid_response",
    "Proof of work failed": "pow_worker_failed",
    "client error": "client_error",
    "transaction failed": "transaction_failed",
    "insufficient balance": "insufficient_balance",
};

function getLocalErrorCode(message) {
    const code = LOCAL_ERROR_CODE_BY_MESSAGE[message];
    if (!code) {
        throw new Error(`[tx] unmapped local error message: ${message}`);
    }
    return code;
}

let __CosmSecp256k1 = null;
let __CosmSha256 = null;
async function ensureCosmCrypto() {
    if (!__CosmSecp256k1 || !__CosmSha256) {
        const { Secp256k1, sha256 } = await ensureCosmCryptoShared();
        __CosmSecp256k1 = Secp256k1;
        __CosmSha256 = sha256;
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

            // Track in-flight block/unblock operations with queue position and action type
            // Map<key, { action: 'block'|'unblock', type: 'user'|'topic'|'post', target: string, queuePosition: number }>
            this.pendingBlocks = new Map();
            this._blockListeners = new Set();

            // Track in-flight delete-account operations with queue position
            // Map<key, { action: 'delete', type: 'account', target: string, queuePosition: number }>
            this.pendingDeletes = new Map();
            this._deleteListeners = new Set();

            // Track in-flight enable/disable agent operations
            // Map<agentAddress, { action: 'enable'|'disable', target: string, queuePosition: number }>
            this.pendingAgents = new Map();
            this._agentListeners = new Set();

            // Track in-flight votes by post ID: Map<postId, { direction: number, queuePosition: number }>
            this.pendingVotes = new Map();
            this._voteListeners = new Set();

            // Track in-flight send_tokens operations
            // Map<key, { target: string, amount: number, queuePosition: number }>
            this.pendingSends = new Map();
            this._sendListeners = new Set();

            // Track in-flight subscribe operations
            // Map<key, { target: string, action: 'subscribe'|'gift', queuePosition: number }>
            this.pendingSubscribes = new Map();
            this._subscribeListeners = new Set();

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

    _fail(message, extra) {
        const code = getLocalErrorCode(message);
        const payload = { success: false, error_code: code, error: message };
        if (extra && typeof extra === 'object') {
            Object.assign(payload, extra);
        }
        return payload;
    }

    _failFromException(err) {
        if (err && typeof err === 'object' && err.error_code) {
            return {
                success: false,
                error_code: err.error_code,
                error: String(err.error || err.message || err.error_code),
            };
        }
        const msg = String(err?.message || err || "");
        return this._fail("client error", msg ? { details: msg } : undefined);
    }

    _persistUserBalance(balanceVal, { normalizeStorage = false, updateLastOnchain = true } = {}) {
        if (balanceVal === undefined || balanceVal === null) return;

        // Respect balance hold from optimistic deductions (e.g. awards).
        // adjustBalanceOptimistic() writes directly to localStorage and sets a
        // hold — all server-sourced writes must honour that hold so we don't
        // flash the old (higher) balance back to the user.
        const hold = Storage.load('user_balance_hold', null);
        if (hold && typeof hold === 'object') {
            const expiresAt = Number(hold.expires_at_ms);
            const minBalance = Number(hold.min_balance);
            if (Number.isFinite(expiresAt) && Date.now() < expiresAt
                && Number.isFinite(minBalance)) {
                const incoming = Number(balanceVal);
                if (Number.isFinite(incoming) && incoming > minBalance) return;
                Storage.remove('user_balance_hold');
            }
        }

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

    // Send tokens tracking methods
    addSendListener(callback) {
        if (typeof callback === 'function') {
            this._sendListeners.add(callback);
        }
        return () => this._sendListeners.delete(callback);
    }

    _notifySendListeners() {
        const pending = this.getPendingSends();
        this._sendListeners.forEach(cb => {
            try { cb(pending); } catch (_) { }
        });
    }

    getPendingSends() {
        const result = {};
        this.pendingSends.forEach((value, key) => {
            result[key] = value;
        });
        return result;
    }

    isPendingSend(target) {
        const key = `send:${String(target).toLowerCase()}`;
        return this.pendingSends.has(key);
    }

    getPendingSendInfo(target) {
        const key = `send:${String(target).toLowerCase()}`;
        return this.pendingSends.get(key) || null;
    }

    // Subscribe tracking methods
    addSubscribeListener(callback) {
        if (typeof callback === 'function') {
            this._subscribeListeners.add(callback);
        }
        return () => this._subscribeListeners.delete(callback);
    }

    _notifySubscribeListeners() {
        const pending = this.getPendingSubscribes();
        this._subscribeListeners.forEach(cb => {
            try { cb(pending); } catch (_) { }
        });
    }

    getPendingSubscribes() {
        const result = {};
        this.pendingSubscribes.forEach((value, key) => {
            result[key] = value;
        });
        return result;
    }

    isPendingSubscribe(target) {
        const key = `subscribe:${String(target).toLowerCase()}`;
        return this.pendingSubscribes.has(key);
    }

    getPendingSubscribeInfo(target) {
        const key = `subscribe:${String(target).toLowerCase()}`;
        return this.pendingSubscribes.get(key) || null;
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

    // Block tracking methods
    addBlockListener(callback) {
        if (typeof callback === 'function') {
            this._blockListeners.add(callback);
        }
        return () => this._blockListeners.delete(callback);
    }

    _notifyBlockListeners() {
        const pending = this.getPendingBlocks();
        this._blockListeners.forEach(cb => {
            try { cb(pending); } catch (_) { }
        });
    }

    getPendingBlocks() {
        const result = {};
        this.pendingBlocks.forEach((value, key) => {
            result[key] = value;
        });
        return result;
    }

    isPendingBlock(type, target) {
        const key = `${type}:${String(target || '').toLowerCase()}`;
        return this.pendingBlocks.has(key);
    }

    getPendingBlockInfo(type, target) {
        const key = `${type}:${String(target || '').toLowerCase()}`;
        return this.pendingBlocks.get(key) || null;
    }

    // Delete-account tracking methods
    addDeleteListener(callback) {
        if (typeof callback === 'function') {
            this._deleteListeners.add(callback);
        }
        return () => this._deleteListeners.delete(callback);
    }

    _notifyDeleteListeners() {
        const pending = this.getPendingDeletes();
        this._deleteListeners.forEach(cb => {
            try { cb(pending); } catch (_) { }
        });
    }

    getPendingDeletes() {
        const result = {};
        this.pendingDeletes.forEach((value, key) => {
            result[key] = value;
        });
        return result;
    }

    isPendingDelete(target) {
        const key = `account:${String(target || '').toLowerCase()}`;
        return this.pendingDeletes.has(key);
    }

    getPendingDeleteInfo(target) {
        const key = `account:${String(target || '').toLowerCase()}`;
        return this.pendingDeletes.get(key) || null;
    }

    // Agent tracking methods
    addAgentListener(callback) {
        if (typeof callback === 'function') {
            this._agentListeners.add(callback);
        }
        return () => this._agentListeners.delete(callback);
    }

    _notifyAgentListeners() {
        const pending = this.getPendingAgents();
        this._agentListeners.forEach(cb => {
            try { cb(pending); } catch (_) { }
        });
    }

    getPendingAgents() {
        const result = {};
        this.pendingAgents.forEach((value, key) => {
            result[key] = value;
        });
        return result;
    }

    isPendingAgent(agentAddress) {
        const key = String(agentAddress || '').toLowerCase();
        return this.pendingAgents.has(key);
    }

    getPendingAgentInfo(agentAddress) {
        const key = String(agentAddress || '').toLowerCase();
        return this.pendingAgents.get(key) || null;
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
                        if (this.updatePost && this.getPost) {
                            let postKey = tLower;
                            if (!this.getPost(tLower)) {
                                const exactKey = String(target).trim();
                                if (this.getPost(exactKey)) postKey = exactKey;
                            }
                            const serverDir = vote > 0 ? 1 : (vote < 0 ? -1 : 0);
                            const updateData = { direction: serverDir };
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
     * @param {string} [referrerUsername] - Optional referrer username (from /signup?ref=)
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async createUser(usernameRaw, inviteCode = "", referrerUsername = "") {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const username = String(usernameRaw || "").trim();
            if (!username) return this._fail("empty username");

            // Determine subscriber path
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            if (userLevel === 0) {
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
                invite_code: inviteCode || "",
                referrer_username: referrerUsername || "",
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async setUsername(usernameRaw) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const username = String(usernameRaw || "").trim();
            if (!username) return this._fail("empty username");

            // Subscribers do not need parameters; free users do
            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            if (userLevel === 0) {
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
            return this._failFromException(e);
        }
    }

    async setBiography(biographyRaw) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const biography = String(biographyRaw ?? "").trim();

            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits = 0;
            let pow_factor = 0;
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            if (userLevel === 0) {
                const statusData = await Api.get('get_parameters', publicKey ? { address: publicKey } : undefined);
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
                action: 'set_biography',
                biography,
                last_block_hash: userLevel >= 1 ? "" : last_block_hash,
                pow_difficulty: userLevel >= 1 ? 0 : pow_difficulty,
                pow_base_bits,
                pow_factor,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}:${userLevel >= 1 ? "" : last_block_hash}:0`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return this._failFromException(e);
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
            const publicKey = Storage.load("publicKey", "");
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            if (!txhashTrimmed) return this._fail("empty txhash");

            // Check if post is already blocked
            try {
                const blocked = await Api.get('get_user_blocked', { address: publicKey }, { timeoutMs: 5000 });
                const blockedPosts = (blocked?.blocked_posts || []).map(p => String(p).toLowerCase());
                if (blockedPosts.includes(txhashTrimmed)) {
                    return this._fail("post is already blocked");
                }
            } catch (_) { }

            const key = `post:${txhashTrimmed}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("block post already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'block', type: 'post', target: txhashTrimmed, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue block_post", { target: txhashTrimmed, queuePosition });

            const baseTx = {
                action: 'block_post',
                target: txhashTrimmed,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    console.debug("[blocks] resolved block_post", { target: txhashTrimmed, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async unblockPost(txhash) {
        try {
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            if (!txhashTrimmed) return this._fail("empty txhash");
            const key = `post:${txhashTrimmed}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("unblock post already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'unblock', type: 'post', target: txhashTrimmed, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue unblock_post", { target: txhashTrimmed, queuePosition });

            const baseTx = {
                action: 'unblock_post',
                target: txhashTrimmed,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    console.debug("[blocks] resolved unblock_post", { target: txhashTrimmed, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async blockUser(address) {
        try {
            const publicKey = Storage.load("publicKey", "");
            const addressTrimmed = String(address || "").trim().toLowerCase();
            if (!addressTrimmed) return this._fail("empty address");

            // Check if user is already blocked
            try {
                const blocked = await Api.get('get_user_blocked', { address: publicKey }, { timeoutMs: 5000 });
                const blockedUsers = (blocked?.blocked_users || []).map(u => String(u).toLowerCase());
                if (blockedUsers.includes(addressTrimmed)) {
                    return this._fail("user is already blocked");
                }
            } catch (_) { }

            const key = `user:${addressTrimmed}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("block user already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'block', type: 'user', target: addressTrimmed, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue block_user", { target: addressTrimmed, queuePosition });

            const baseTx = {
                action: 'block_user',
                target: addressTrimmed,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    console.debug("[blocks] resolved block_user", { target: addressTrimmed, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async unblockUser(address) {
        try {
            const addressTrimmed = String(address || "").trim().toLowerCase();
            if (!addressTrimmed) return this._fail("empty address");
            const key = `user:${addressTrimmed}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("unblock user already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'unblock', type: 'user', target: addressTrimmed, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue unblock_user", { target: addressTrimmed, queuePosition });

            const baseTx = {
                action: 'unblock_user',
                target: addressTrimmed,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    console.debug("[blocks] resolved unblock_user", { target: addressTrimmed, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async blockTopic(topic) {
        try {
            const publicKey = Storage.load("publicKey", "");
            const topicTrimmed = String(topic || "").trim().toLowerCase();
            if (!topicTrimmed) return this._fail("empty topic");

            // Check if topic is already blocked
            try {
                const blocked = await Api.get('get_user_blocked', { address: publicKey }, { timeoutMs: 5000 });
                const blockedTopics = (blocked?.blocked_topics || []).map(t => String(t).toLowerCase());
                if (blockedTopics.includes(topicTrimmed)) {
                    return this._fail("topic is already blocked");
                }
            } catch (_) { }

            const key = `topic:${topicTrimmed}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("block topic already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'block', type: 'topic', target: topicTrimmed, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue block_topic", { target: topicTrimmed, queuePosition });

            const baseTx = {
                action: 'block_topic',
                topic: topicTrimmed,
                target: "",
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    // Mutual exclusion: blocking a topic unfollows it on-chain.
                    // Update sidebar immediately so the blocked topic disappears.
                    if (result?.success) {
                        // Delay all feed/sidebar updates so the caller can show success UI first
                        setTimeout(() => {
                            notifyTopicsUpdated({ removed: topicTrimmed });
                            invalidateSubCache();
                            window.dispatchEvent(new CustomEvent('topicBlocked', { detail: { topic: topicTrimmed } }));
                        }, 3200);
                    }
                    console.debug("[blocks] resolved block_topic", { target: topicTrimmed, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async unblockTopic(topic) {
        try {
            const topicTrimmed = String(topic || "").trim().toLowerCase();
            if (!topicTrimmed) return this._fail("empty topic");
            const key = `topic:${topicTrimmed}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("unblock topic already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'unblock', type: 'topic', target: topicTrimmed, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue unblock_topic", { target: topicTrimmed, queuePosition });

            const baseTx = {
                action: 'unblock_topic',
                topic: topicTrimmed,
                target: "",
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    if (result?.success) {
                        window.dispatchEvent(new CustomEvent('topicUnblocked', { detail: { topic: topicTrimmed } }));
                    }
                    console.debug("[blocks] resolved unblock_topic", { target: topicTrimmed, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    followUser(userAddress) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve(this._fail("Not logged in"));
        }

        const userTrimmed = String(userAddress || "").trim().toLowerCase();
        if (!userTrimmed) {
            return Promise.resolve(this._fail("empty user address"));
        }

        const key = `user:${userTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve(this._fail("follow user already in progress"));
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
            return Promise.resolve(this._fail("Not logged in"));
        }

        const userTrimmed = String(userAddress || "").trim().toLowerCase();
        if (!userTrimmed) {
            return Promise.resolve(this._fail("empty user address"));
        }

        const key = `user:${userTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve(this._fail("unfollow user already in progress"));
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
            return Promise.resolve(this._fail("Not logged in"));
        }

        const topicTrimmed = String(topic || "").trim().toLowerCase();
        if (!topicTrimmed) {
            return Promise.resolve(this._fail("empty topic"));
        }

        const key = `topic:${topicTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve(this._fail("follow topic already in progress"));
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
            return Promise.resolve(this._fail("Not logged in"));
        }

        const topicTrimmed = String(topic || "").trim().toLowerCase();
        if (!topicTrimmed) {
            return Promise.resolve(this._fail("empty topic"));
        }

        const key = `topic:${topicTrimmed}`;
        if (this.pendingFollows.has(key)) {
            return Promise.resolve(this._fail("unfollow topic already in progress"));
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
                if (result?.success) {
                    notifyTopicsUpdated({ removed: topicTrimmed });
                    invalidateSubCache();
                }
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _followKey: key };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    enableAgent(agentAddress) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve(this._fail("Not logged in"));
        }

        const agentTrimmed = String(agentAddress || "").trim().toLowerCase();
        if (!agentTrimmed) {
            return Promise.resolve(this._fail("empty agent address"));
        }

        if (this.pendingAgents.has(agentTrimmed)) {
            return Promise.resolve(this._fail("enable agent already in progress"));
        }

        const queuePosition = this.totalTransactions + 1;
        this.pendingAgents.set(agentTrimmed, { action: 'enable', target: agentTrimmed, queuePosition });
        this._notifyAgentListeners();
        console.debug("[agents] enqueue enable_agent", { target: agentTrimmed, queuePosition });

        const baseTx = {
            action: 'enable_agent',
            agent: agentTrimmed,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                this.pendingAgents.delete(agentTrimmed);
                this._notifyAgentListeners();
                console.debug("[agents] resolved enable_agent", { target: agentTrimmed, success: !!result?.success, error: result?.error });
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _agentKey: agentTrimmed };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    disableAgent(agentAddress) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve(this._fail("Not logged in"));
        }

        const agentTrimmed = String(agentAddress || "").trim().toLowerCase();
        if (!agentTrimmed) {
            return Promise.resolve(this._fail("empty agent address"));
        }

        if (this.pendingAgents.has(agentTrimmed)) {
            return Promise.resolve(this._fail("disable agent already in progress"));
        }

        const queuePosition = this.totalTransactions + 1;
        this.pendingAgents.set(agentTrimmed, { action: 'disable', target: agentTrimmed, queuePosition });
        this._notifyAgentListeners();
        console.debug("[agents] enqueue disable_agent", { target: agentTrimmed, queuePosition });

        const baseTx = {
            action: 'disable_agent',
            agent: agentTrimmed,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                this.pendingAgents.delete(agentTrimmed);
                this._notifyAgentListeners();
                console.debug("[agents] resolved disable_agent", { target: agentTrimmed, success: !!result?.success, error: result?.error });
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _agentKey: agentTrimmed };
            this.transactions.push(transaction);
            this.totalTransactions += 1;
            this.processTransactions();
        });
    }

    setAgents(agents, { triggerAgent } = {}) {
        const publicKey = Storage.load("publicKey", "");
        const seedPhrase = seedVault.getSeed() || "";
        if (!publicKey || !seedPhrase) {
            updateNotification("Not logged in");
            return Promise.resolve(this._fail("Not logged in"));
        }

        if (!Array.isArray(agents)) {
            return Promise.resolve(this._fail("agents must be an array"));
        }

        const normalized = agents.map(a => String(a || "").trim().toLowerCase()).filter(Boolean);
        const triggerKey = triggerAgent ? String(triggerAgent).toLowerCase() : null;

        const queuePosition = this.totalTransactions + 1;
        if (triggerKey) {
            this.pendingAgents.set(triggerKey, { action: 'set_agents', agents: normalized, queuePosition });
        } else {
            this.pendingAgents.set('__set_agents__', { action: 'set_agents', agents: normalized, queuePosition });
        }
        this._notifyAgentListeners();
        console.debug("[agents] enqueue set_agents", { count: normalized.length, triggerAgent: triggerKey, queuePosition });

        const baseTx = {
            action: 'set_agents',
            agents: normalized,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                if (triggerKey) {
                    this.pendingAgents.delete(triggerKey);
                } else {
                    this.pendingAgents.delete('__set_agents__');
                }
                this._notifyAgentListeners();
                console.debug("[agents] resolved set_agents", { success: !!result?.success, error: result?.error });
                resolve(result);
            };
            const pendingKey = triggerKey || '__set_agents__';
            const transaction = { ...baseTx, _resolve: wrappedResolve, _agentKey: pendingKey };
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
            if (!txhashTrimmed) return this._fail("empty target");
            if (!why) return this._fail("empty reason");

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
            return this._failFromException(e);
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
            const _seed = seedVault.getSeed() || ""; // eslint-disable-line no-unused-vars
            const publicKey = Storage.load("publicKey", "");
            const targetTrimmed = String(targetAddress || "").trim().toLowerCase();

            if (!targetTrimmed || !amountMirage || amountMirage <= 0) {
                return this._fail("Invalid recipient or amount");
            }

            // Validate mirage1 address
            if (!targetTrimmed.startsWith("mirage1")) {
                return this._fail("Recipient must be a mirage1 address");
            }

            // Convert MIRAGE to umirage
            const amountUmirage = Math.floor(amountMirage * 1000000);
            if (amountUmirage < 1000) {
                return this._fail("Minimum amount is 0.001 MIRAGE");
            }

            updateNotification("Sending tokens");

            const [statusData] = await Promise.all([
                Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
            ]);
            const balance = statusData?.balance || 0;

            // Check balance for amount only (no gas fee for level >= 1 users)
            const totalNeeded = amountUmirage;

            if (balance < totalNeeded) {
                const haveM = (balance / 1000000).toFixed(3);
                const needM = (totalNeeded / 1000000).toFixed(3);
                return this._fail("insufficient balance", { balance: haveM, needed: needM });
            }

            const sendKey = `send:${targetTrimmed}`;
            if (this.pendingSends.has(sendKey)) {
                return this._fail("send tokens already in progress");
            }
            const queuePosition = this.totalTransactions + 1;
            this.pendingSends.set(sendKey, { target: targetTrimmed, amount: amountUmirage, queuePosition });
            this._notifySendListeners();
            console.debug("[send_tokens] enqueue", { target: targetTrimmed, amount: amountUmirage, queuePosition });

            const baseTx = {
                action: 'send_tokens',
                target: targetTrimmed,
                amount: amountUmirage,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingSends.delete(sendKey);
                    this._notifySendListeners();
                    console.debug("[send_tokens] resolved", {
                        target: targetTrimmed,
                        success: !!result?.success,
                        error: result?.error,
                    });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    /**
     * Give an award to a post or comment (burn-only).
     * @param {string} targetPostId - The post/comment tx hash to award
     * @param {string} awardType - One of the configured award types (e.g. "quality_post")
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async giveAward(targetPostId, awardType) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const target = String(targetPostId || "").trim().toLowerCase();
            const type = String(awardType || "").trim();

            if (!target || !type) {
                return this._fail("Missing target or award type");
            }

            updateNotification("Giving award");

            const [statusData] = await Promise.all([
                Api.get('get_parameters', publicKey ? { address: publicKey } : undefined),
            ]);
            let last_block_hash = statusData?.last_block_hash || "";
            let pow_difficulty = requirePowDifficulty(statusData?.pow_difficulty);
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            if (userLevel >= 1) {
                pow_difficulty = 0;
                last_block_hash = "";
            }
            console.debug('[TransactionHandler] giveAward.submit', { target, award_type: type, user_level: userLevel });

            const tx = {
                action: 'award',
                target,
                award_type: type,
                last_block_hash,
                pow_difficulty,
                pow_base_bits: 0,
                pow_factor: 0,
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;

            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return this._failFromException(e);
        }
    }

    /**
     * Subscribe (or gift a subscription) to a tier level.
     * @param {number} level - Target paid subscription level (1=Subscriber, 10=Agent)
     * @param {number} monthlyFeeUmirage - The monthly fee in umirage for the target tier (unused, kept for API compatibility)
     * @param {string} [target] - Optional target address to gift the subscription to
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async subscribe(level, monthlyFeeUmirage, target) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const targetLevel = Number(level);

            if (targetLevel !== 1 && targetLevel !== 10) {
                return this._fail("Invalid level");
            }

            const targetTrimmed = String(target || "").trim().toLowerCase();
            updateNotification(targetTrimmed ? "Gifting subscription" : "Subscribing");

            const last_block_hash = "";
            const tx = {
                action: 'subscribe',
                level: targetLevel,
                target: targetTrimmed,
                last_block_hash,
                pow_difficulty: 0, // PoW not allowed for subscribe
                timestamp: Math.max(0, Date.now() - 15000),
            };

            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const challenge = `${derivedAddress}:${last_block_hash}:0`;

            const recipient = targetTrimmed || String(derivedAddress || "").trim().toLowerCase();
            const subKey = `subscribe:${recipient}`;
            if (this.pendingSubscribes.has(subKey)) {
                return this._fail("subscription already in progress");
            }
            const queuePosition = this.totalTransactions + 1;
            this.pendingSubscribes.set(subKey, {
                target: recipient,
                action: targetTrimmed ? 'gift' : 'subscribe',
                queuePosition,
            });
            this._notifySubscribeListeners();
            console.debug("[subscribe] enqueue", { target: recipient, action: targetTrimmed ? 'gift' : 'subscribe', queuePosition });

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingSubscribes.delete(subKey);
                    this._notifySubscribeListeners();
                    console.debug("[subscribe] resolved", {
                        target: recipient,
                        success: !!result?.success,
                        error: result?.error,
                    });
                    resolve(result);
                };
                this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false)
                    .then(wrappedResolve)
                    .catch((err) => wrappedResolve(this._failFromException(err)));
            });
        } catch (e) {
            return this._failFromException(e);
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
            return this._failFromException(e);
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
            if (!chain) return this._fail("destination_chain required");

            const address = String(destinationAddress || "").trim();
            if (!address) return this._fail("destination_address required");

            const amount = Number(amountUmirage) || 0;
            if (amount <= 0) return this._fail("amount must be positive");

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
            return this._failFromException(e);
        }
    }

    /**
     * Delete the current user's account (permanent).
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async deleteUser() {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            if (!seedPhrase) {
                return this._fail("missing recovery phrase");
            }
            const derivedAddress = derivePublicKeyFromSeed(seedPhrase);
            const target = String(derivedAddress || "").trim().toLowerCase();
            if (!target) return this._fail("invalid signer address");
            if (!target.startsWith("mirage1")) return this._fail("invalid address");

            const key = `account:${target}`;
            if (this.pendingDeletes.has(key)) {
                return this._fail("delete account already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingDeletes.set(key, { action: 'delete', type: 'account', target, queuePosition });
            this._notifyDeleteListeners();
            console.debug("[delete_user] enqueue", { target, queuePosition });

            const baseTx = {
                action: 'delete_user',
                target,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingDeletes.delete(key);
                    this._notifyDeleteListeners();
                    console.debug("[delete_user] resolved", { target, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _deleteKey: key };
                this.transactions.push(transaction);
                this.totalTransactions += 1;
                this.processTransactions();
            });
        } catch (e) {
            return this._failFromException(e);
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
            if (!txhashTrimmed) return this._fail("empty txhash");

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
            return this._failFromException(e);
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
            if (!overrideLower || overrideLower.length !== 64) return this._fail("invalid override");
            const content = String(changes?.content || "").trim();
            const title = String(changes?.title || "").trim();
            const topic = String(changes?.topic || "").trim();
            const target = String(changes?.target || "").trim();
            const tagRaw = String(changes?.tag || "").trim().toLowerCase();
            const media = Array.isArray(changes?.media) ? changes.media : [];
            if (!ALLOWED_TAGS.has(tagRaw)) return this._fail("invalid tag");

            const userLevelE = Number(Storage.load('user_level', '0')) || 0;
            let last_block_hash_e = "";
            let pow_difficulty_e = 0;
            let pow_base_bits_e = 0;
            let pow_factor_e = 0;
            if (userLevelE === 0) {
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
            return this._failFromException(e);
        }
    }


    /**
     * Agent-only: annotate (overlay edit) an existing post
     * @param {string} overrideId - txhash of the post being annotated
     * @param {{topic?: string, title?: string, content?: string, tag?: string, media?: string[], appendix?: string}} fields
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async annotatePost(overrideId, fields) {
        try {
            const seedPhrase = seedVault.getSeed() || "";
            const publicKey = Storage.load("publicKey", "");
            const overrideLower = String(overrideId || "").trim().toLowerCase();
            if (!overrideLower || overrideLower.length !== 64) return this._fail("invalid override");
            const topic = String(fields?.topic ?? ".").trim();
            const title = String(fields?.title ?? ".").trim();
            const content = String(fields?.content ?? ".").trim();
            const tag = String(fields?.tag ?? ".").trim();
            const appendix = String(fields?.appendix ?? ".").trim();
            const media = Array.isArray(fields?.media) ? fields.media : ["."];

            const tx = {
                action: 'annotate_post',
                override: overrideLower,
                topic,
                title,
                content,
                tag,
                media,
                appendix,
                last_block_hash: "",
                pow_difficulty: 0,
                pow_base_bits: 0,
                pow_factor: 0,
                timestamp: Math.max(0, Date.now() - 15000),
            };
            const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
            const derivedAddress = (function () { try { return derivePublicKeyFromSeed(seedPhrase); } catch (_) { return publicKey; } })();
            const challenge = `${derivedAddress}::0`;
            const result = await this.performTransaction(tx, challenge, privateKeyHex, derivedAddress, false);
            return result;
        } catch (e) {
            return this._failFromException(e);
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
     * Returns true if the cached chainConfig is missing or older than 4 hours.
     */
    needsChainConfigRefresh() {
        if (!localStorage.getItem('chainConfig')) return true;
        const cachedAt = parseInt(Storage.load('chain_config_cached_at', '0'));
        return Date.now() - cachedAt > 4 * 3600 * 1000;
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
        if (data.referral_precheck_enabled !== undefined) {
            Storage.save('referral_precheck_enabled', data.referral_precheck_enabled === true);
        }
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
            return Promise.resolve(this._fail("Not logged in"));
        }

        const postKey = String(parentId || '').toLowerCase();

        // Check if vote already pending for this post
        if (this.pendingVotes.has(postKey)) {
            return Promise.resolve(this._fail("Vote already pending"));
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
                return this._fail("Not logged in");
            }

            const cleanTag = typeof tag === 'string' ? tag.trim().toLowerCase() : "";
            if (!ALLOWED_TAGS.has(cleanTag)) {
                return this._fail("invalid tag");
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
            return this._failFromException(e);
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
                return this._fail("Not logged in");
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
            return this._failFromException(e);
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
            const { _resolve: _ignored, _followKey: _ignored2, _blockKey: _ignored3, _deleteKey: _ignored4, _agentKey: _ignored5, ...transaction } = queued;
            const giftTarget = String(transaction.target || '').trim();
            const _isGiftSubscribe = transaction.action === 'subscribe' && giftTarget !== ''; // eslint-disable-line no-unused-vars
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
                    if (_resolve) _resolve(this._fail("transaction failed", { details: msg }));
                    hadFailure = true;
                    break;
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
            else if (transaction.action === "block_user" || transaction.action === "unblock_user") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "block_post" || transaction.action === "unblock_post") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "block_topic" || transaction.action === "unblock_topic") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target || "",
                    topic: transaction.topic || "",
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "enable_agent" || transaction.action === "disable_agent") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    agent: (transaction.agent || "").toLowerCase(),
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "set_agents") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    agents: (transaction.agents || []).map(a => String(a).toLowerCase()),
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "delete_user") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target || "",
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "send_tokens") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target,
                    amount: transaction.amount,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "set_biography") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    biography: transaction.biography ?? "",
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
                const grpcMatch = errMsg.match(/details\s*=\s*"([^"]+)"/);
                const cleanMsg = grpcMatch && grpcMatch[1] ? grpcMatch[1] : errMsg;
                if (_resolve) _resolve(this._fail("transaction failed", cleanMsg ? { details: cleanMsg } : undefined));
                hadFailure = true;
                break;
            }
            if (!result || !result.success) {
                if (_resolve) {
                    if (result && result.error_code) {
                        _resolve(result);
                    } else {
                        const msg = String(result && result.error ? result.error : 'Transaction failed');
                        _resolve(this._fail("transaction failed", msg ? { details: msg } : undefined));
                    }
                }
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
    canonicalPost({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, title, content, tag, media, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
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
    canonicalEdit({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, title, content, tag, override, media, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
            tag102, encStr(title || ""),
            tag103, encStr(content || ""),
            tag104, encStr(tag || ""),
            tag105, encStr(override || ""),
            ...mediaParts,
        );
    }

    canonicalAnnotate({ pub_bytes, last_block_hash, difficulty, proof, timestamp, topic, title, content, tag, override, media, appendix, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgAnnotate\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);
        const tag101 = Uint8Array.from([101]);
        const tag102 = Uint8Array.from([102]);
        const tag103 = Uint8Array.from([103]);
        const tag104 = Uint8Array.from([104]);
        const tag105 = Uint8Array.from([105]);
        const tag106 = Uint8Array.from([106]);
        const tag107 = Uint8Array.from([107]);
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag101, encStr(topic || ""),
            tag102, encStr(title || ""),
            tag103, encStr(content || ""),
            tag104, encStr(tag || ""),
            tag105, encStr(override || ""),
            ...mediaParts,
            tag107, encStr(appendix || ""),
        );
    }

    // Build canonical bytes for MsgSetUsername (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalSetUsername({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, username, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(username || ""),
        );
    }

    canonicalSetBiography({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, biography, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetBiography\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(biography ?? ""),
        );
    }

    // Build canonical bytes for MsgEnableAgent
    canonicalEnableAgent({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, agent, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgEnableAgent\x00");
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(agent || ""),
        );
    }

    // Build canonical bytes for MsgDisableAgent
    canonicalDisableAgent({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, agent, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgDisableAgent\x00");
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(agent || ""),
        );
    }

    // Build canonical bytes for MsgSetAgents
    canonicalSetAgents({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, agents, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetAgents\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]);
        const agentParts = [];
        for (const a of (agents || [])) {
            agentParts.push(tag101, encStr(a));
        }
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            ...agentParts,
        );
    }

    // Build canonical bytes for MsgFollowUser
    canonicalFollowUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, user, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(user || ""),
        );
    }

    // Build canonical bytes for MsgUnfollowUser
    canonicalUnfollowUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, user, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(user || ""),
        );
    }

    // Build canonical bytes for MsgFollowTopic
    canonicalFollowTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgUnfollowTopic
    canonicalUnfollowTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgUnblockPost
    canonicalUnblockPost({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgUnblockUser
    canonicalUnblockUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgBlockPost (v1.5: no block bool)
    canonicalBlockPost({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgBlockUser (v1.5: no block bool)
    canonicalBlockUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgBlockTopic
    canonicalBlockTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgUnblockTopic
    canonicalUnblockTopic({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
            tag101, encStr(topic || ""),
        );
    }

    // Build canonical bytes for MsgDelete (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalDelete({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgDeleteUser (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalDeleteUser({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgDeleteUser\x00");
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
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(target || ""),
        );
    }

    // Build canonical bytes for MsgSendTokens (must match chain ante)
    // IMPORTANT: Authority (tag 1) is NOT included - it's set by backend to validator/node address
    canonicalSendTokens({ pub_bytes, last_block_hash, difficulty, proof, timestamp, sender, target, amount, nonce }) {
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
            Uint8Array.from([7]), uvarint64(nonce),
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

        // derive keys
        const privBytes = new Uint8Array(privateKeyHex.match(/.{1,2}/g).map((b) => parseInt(b, 16)));
        const pubBytes = secp256k1GetPublicKey(privBytes, true);
        // Use proper binary-to-base64 encoding
        const pubB64 = btoa(Array.from(pubBytes).map(b => String.fromCharCode(b)).join(''));

        const envelopeNonce = Number(transaction.envelope_nonce) || generateEnvelopeNonce();
        let toRelay = { ...transaction, pubkey: pubB64, pow: proof, signature: "", envelope_nonce: envelopeNonce };

        try {
            // Compute canonical bytes per Tx type and sign
            const action = transaction.action;
            let msgName = '';
            if (action === 'create_vote') msgName = 'MsgVote';
            else if (action === 'create_post' || action === 'create_comment') msgName = 'MsgPost';
            else if (action === 'enable_agent') msgName = 'MsgEnableAgent';
            else if (action === 'disable_agent') msgName = 'MsgDisableAgent';
            else if (action === 'set_agents') msgName = 'MsgSetAgents';
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
            else if (action === 'delete_user') msgName = 'MsgDeleteUser';
            else if (action === 'send_tokens') msgName = 'MsgSendTokens';
            else if (action === 'set_username') msgName = 'MsgSetUsername';
            else if (action === 'set_biography') msgName = 'MsgSetBiography';
            else if (action === 'report') msgName = 'MsgReport';
            else if (action === 'edit_post') msgName = 'MsgEdit';
            else if (action === 'annotate_post') msgName = 'MsgAnnotate';
            else if (action === 'subscribe') msgName = 'MsgSubscribe';
            else if (action === 'set_auto_renewal') msgName = 'MsgSetAutoRenewal';
            else if (action === 'bridge_burn') msgName = 'MsgBridgeBurn';
            else if (action === 'award') msgName = 'MsgAward';
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
                };
                if (transaction.invite_code) {
                    toRelay.invite_code = transaction.invite_code;
                }
                if (transaction.referrer_username) {
                    toRelay.referrer_username = transaction.referrer_username;
                }
                endpoint = 'core/set_username';
            } else if (msgName === 'MsgSetBiography') {
                const difficulty = resolveTxDifficulty(transaction);
                const canon = this.canonicalSetBiography({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: signerAddress,
                    biography: transaction.biography ?? "",
                    nonce: envelopeNonce,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    biography: transaction.biography ?? "",
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/set_biography';
            } else if (msgName === 'MsgEnableAgent') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const agentLower = (transaction.agent || "").toLowerCase();
                const canon = this.canonicalEnableAgent({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    agent: agentLower,
                    nonce: envelopeNonce,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    agent: agentLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/enable_agent';
            } else if (msgName === 'MsgDisableAgent') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const agentLower = (transaction.agent || "").toLowerCase();
                const canon = this.canonicalDisableAgent({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    agent: agentLower,
                    nonce: envelopeNonce,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    agent: agentLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/disable_agent';
            } else if (msgName === 'MsgSetAgents') {
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = signerAddress.toLowerCase();
                const agentsLower = (transaction.agents || []).map(a => String(a).toLowerCase());
                const canon = this.canonicalSetAgents({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    agents: agentsLower,
                    nonce: envelopeNonce,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    agents: agentsLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/set_agents';
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/delete_post';
            } else if (msgName === 'MsgDeleteUser') {
                // Sign relay for delete user (must match chain ante)
                const difficulty = resolveTxDifficulty(transaction);
                const targetLower = (transaction.target || "").toLowerCase();
                const canon = this.canonicalDeleteUser({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetLower,
                    nonce: envelopeNonce,
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
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/delete_user';
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
                    nonce: envelopeNonce,
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
                    envelope_nonce: envelopeNonce,
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    envelope_nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
                    nonce: envelopeNonce,
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
            } else if (msgName === 'MsgAnnotate') {
                const topic = transaction.topic || "";
                const mediaArr = Array.isArray(transaction.media) ? transaction.media : [];
                const canon = this.canonicalAnnotate({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: 0,
                    proof: 0,
                    timestamp: transaction.timestamp,
                    topic: topic,
                    title: transaction.title || "",
                    content: transaction.content || "",
                    tag: transaction.tag || "",
                    override: String(transaction.override || '').toLowerCase(),
                    media: mediaArr,
                    appendix: transaction.appendix || "",
                    nonce: envelopeNonce,
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
                    appendix: transaction.appendix || "",
                };
                endpoint = 'core/annotate';
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/vote';
            } else if (msgName === 'MsgSubscribe') {
                // Sign relay for subscribe (must match chain ante_metasig)
                // Note: PoW is NOT allowed for MsgSubscribe - must pay with tokens
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
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgSubscribe\x00");
                const tag2 = Uint8Array.from([2]);   // envelope_pubkey
                const tag3 = Uint8Array.from([3]);   // envelope_block_hash
                const tag4 = Uint8Array.from([4]);   // envelope_difficulty (always 0)
                const tag5 = Uint8Array.from([5]);   // envelope_pow (always 0 for subscribe)
                const tag6 = Uint8Array.from([6]);   // envelope_timestamp
                const tag100 = Uint8Array.from([100]); // level
                const tag101 = Uint8Array.from([101]); // target
                const targetLevel = Number(transaction.level || 0);
                const targetStr = (transaction.target || "").trim().toLowerCase();
                const targetBytes = new TextEncoder().encode(targetStr);
                const canonParts = [
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(0), // difficulty always 0 for subscribe
                    tag5, uvarint(0), // pow always 0 for subscribe
                    tag6, uvarint64(transaction.timestamp || 0),
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, uvarint(targetLevel),
                ];
                if (targetStr) {
                    canonParts.push(tag101, encBytes(targetBytes));
                }
                const canon = concat(...canonParts);
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
                    envelope_nonce: envelopeNonce,
                };
                if (targetStr) {
                    toRelay.target = targetStr;
                }
                endpoint = 'core/subscribe';
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    envelope_nonce: envelopeNonce,
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'bridge/burn';
            } else if (msgName === 'MsgAward') {
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
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgAward\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag5 = Uint8Array.from([5]);
                const tag6 = Uint8Array.from([6]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                const canon = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag5, uvarint(Number(proof)),
                    tag6, uvarint64(transaction.timestamp || 0),
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(transaction.award_type || ""),
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
                    target: transaction.target || "",
                    award_type: transaction.award_type || "",
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/award';
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
                }
                resolve({ success: success, tx_hash: txHash, result: out, error: out?.error, error_code: out?.error_code });
                return;
            } catch (e) {
                throw e;
            }
        } catch (error) {
            console.error('Transaction error:', error);
            const errMsg = String(error && error.message ? error.message : error);
            const errStr = String(error);
            const fullErr = errMsg + ' ' + errStr;
            if (/pow_required/i.test(fullErr)) {
                console.warn('Subscription status mismatch detected - clearing cached user_level');
                try {
                    Storage.save('user_level', '0');
                    window.dispatchEvent(new CustomEvent('subscriptionStatusChanged', { detail: { level: 0 } }));
                } catch (_) { }
            }
            let cleanMsg = errMsg;
            const grpcMatch = fullErr.match(/details\s*=\s*"([^"]+)"/);
            if (grpcMatch && grpcMatch[1]) {
                cleanMsg = grpcMatch[1];
            }
            resolve({
                success: false,
                error: cleanMsg || error.message,
                error_code: error.error_code,
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

            // Generate envelope nonce once — used in both PoW baseBytes and signing canonical bytes
            const envelopeNonce = generateEnvelopeNonce();
            transaction.envelope_nonce = envelopeNonce;

            // Subscribers (level >= 1) skip PoW — chain trusts them.
            // Fee-only actions (subscribe, set_auto_renewal) never use PoW regardless of level.
            // NOTE: pow_difficulty=0 for a free user means "base difficulty" (0 extra steps),
            // which still requires computing a valid argon2 hash.  Do NOT skip PoW for that.
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            const NO_POW_ACTIONS = new Set(['subscribe', 'set_auto_renewal', 'award']);
            const canSkipPow = !forcePow && (userLevel >= 1 || NO_POW_ACTIONS.has(transaction.action));

            // Inform UI that we are starting a transaction
            this._setStatus("preparing");

            if (canSkipPow) {
                // Skip PoW computation for subscribers (PoW fields ignored by backend/chain)
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
                    } catch (err) {
                        const msg = String(err && err.message ? err.message : err);
                        wrapResolve(this._fail("transaction failed", msg ? { details: msg } : undefined));
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(topic),
                    tag102, encStr(transaction.title || ""),
                    tag103, encStr(transaction.content || ""),
                    tag104, encStr(transaction.tag || ""),
                    ...mediaParts,
                );
            } else if (action === 'enable_agent' || action === 'disable_agent') {
                const prefix = new TextEncoder().encode(
                    action === 'enable_agent'
                        ? "mirage.core.v1:MsgEnableAgent\x00"
                        : "mirage.core.v1:MsgDisableAgent\x00"
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(signerAddress.toLowerCase()),
                    tag101, encStr((transaction.agent || "").toLowerCase()),
                );
            } else if (action === 'set_agents') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgSetAgents\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                const agentParts = [];
                for (const a of (transaction.agents || [])) {
                    agentParts.push(tag101, encStr(String(a).toLowerCase()));
                }
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(signerAddress.toLowerCase()),
                    ...agentParts,
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(transaction.target || ""),
                );
            } else if (action === 'delete_user') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgDeleteUser\x00");
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
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
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(topic),
                    tag102, encStr(transaction.title || ""),
                    tag103, encStr(transaction.content || ""),
                    tag104, encStr(transaction.tag || ""),
                    tag105, encStr(String(transaction.override || "").toLowerCase()),
                    ...mediaParts,
                );
            } else if (action === 'annotate_post') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgAnnotate\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag5 = Uint8Array.from([5]);
                const tag6 = Uint8Array.from([6]);
                const tag101 = Uint8Array.from([101]);
                const tag102 = Uint8Array.from([102]);
                const tag103 = Uint8Array.from([103]);
                const tag104 = Uint8Array.from([104]);
                const tag105 = Uint8Array.from([105]);
                const tag106 = Uint8Array.from([106]);
                const tag107 = Uint8Array.from([107]);
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
                    tag5, uvarint(0),
                    tag6, uvarint64(transaction.timestamp || 0),
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag101, encStr(transaction.topic || ""),
                    tag102, encStr(transaction.title || ""),
                    tag103, encStr(transaction.content || ""),
                    tag104, encStr(transaction.tag || ""),
                    tag105, encStr(String(transaction.override || "").toLowerCase()),
                    ...mediaParts,
                    tag107, encStr(transaction.appendix || ""),
                );
            } else if (action === 'subscribe') {
                // subscribe should NEVER use PoW - it must be paid with tokens
                // This branch should not be reached, but handle gracefully
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgSubscribe\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag5 = Uint8Array.from([5]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                const targetStr = (transaction.target || "").trim().toLowerCase();
                const targetBytes = new TextEncoder().encode(targetStr);
                const parts = [
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(0), // difficulty always 0
                    tag5, uvarint(0),
                    tag100, uvarint(Number(transaction.level) || 0),
                ];
                if (targetStr) {
                    parts.push(tag101, encBytes(targetBytes));
                }
                baseBytes = concat(...parts);
            } else {
                throw new Error(`Unknown transaction action: "${action}". Must be one of: create_vote, create_post, create_comment, set_username, enable_agent, disable_agent, set_agents, follow_user, unfollow_user, follow_topic, unfollow_topic, block_post, unblock_post, block_user, unblock_user, block_topic, unblock_topic, delete_post, delete_user, send_tokens, report, edit_post, annotate_post, subscribe, set_auto_renewal`);
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
                    updateNotification(`Processing transaction (${taken.toFixed(1)}s)`);
                else
                    updateNotification(`Processing tx ${this.processedTransactions}/${this.totalTransactions} (${taken.toFixed(1)}s)`);
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
                wrapResolve(this._fail("Proof of work took too long (>60s). Your device may be too slow, or the network difficulty is too high. Please try again later."));
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

                const workerData = e ? e.data : null;
                if (workerData && typeof workerData === 'object' && workerData.error) {
                    try { console.error('[PoW] worker error', workerData); } catch (_) { }
                    updateNotification("PoW failed. Please try again.", 5.0, true);
                    wrapResolve(this._fail("Proof of work failed", { details: String(workerData.error || "") }));
                    return;
                }
                if (typeof workerData !== 'number' || !Number.isFinite(workerData)) {
                    try { console.error('[PoW] invalid worker response', workerData); } catch (_) { }
                    updateNotification("PoW failed. Please try again.", 5.0, true);
                    wrapResolve(this._fail("Proof of work failed: invalid worker response."));
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
export { TransactionHandler };
