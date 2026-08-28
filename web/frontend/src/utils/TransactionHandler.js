import { updateNotification } from "../utils/notifications.js";
import Storage from './Storage';
import seedVault from './SeedVault';
import { getPublicKey as secp256k1GetPublicKey } from '@noble/secp256k1';
import { derivePrivateKeyFromSeed, deriveKeysFromSeed, requireValidMnemonic } from './CryptoUtils.js';
import { getSessionGeneration } from './sessionLifecycle';
import { peekHandoffByPurpose } from './onboardingSession';
import Api from './api';
import { notifyTopicsUpdated, invalidateCache as invalidateSubCache } from './Subscriptions';
import { generateEnvelopeNonce, buildCanonical, encStr, uvarint64 } from './canonicalEncoding';
import { ensureCosmCrypto as ensureCosmCryptoShared } from './cosmCrypto';
import { curationPendingKey, invalidateCurationReads, requireCommunitySlug, requireTeamId } from './curation';

const ALLOWED_TAGS = new Set(["", "sensitive", "adult", "gore", "violence", "death"]);

const CURATION_TX_SPECS = Object.freeze({
    create_curation_team: ['MsgCreateCurationTeam', 'core/create_curation_team', [['community', 100, 'string'], ['name', 101, 'string'], ['description', 102, 'string'], ['policy', 103, 'string']]],
    set_curation_team_profile: ['MsgSetCurationTeamProfile', 'core/set_curation_team_profile', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['name', 102, 'string'], ['description', 103, 'string'], ['policy', 104, 'string']]],
    invite_curator: ['MsgInviteCurator', 'core/invite_curator', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['target', 102, 'string']]],
    revoke_curator_invite: ['MsgRevokeCuratorInvite', 'core/revoke_curator_invite', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['target', 102, 'string']]],
    accept_curator_invite: ['MsgAcceptCuratorInvite', 'core/accept_curator_invite', [['community', 100, 'string'], ['team_id', 101, 'uint']]],
    decline_curator_invite: ['MsgDeclineCuratorInvite', 'core/decline_curator_invite', [['community', 100, 'string'], ['team_id', 101, 'uint']]],
    leave_curation_team: ['MsgLeaveCurationTeam', 'core/leave_curation_team', [['community', 100, 'string'], ['team_id', 101, 'uint']]],
    remove_curator: ['MsgRemoveCurator', 'core/remove_curator', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['target', 102, 'string']]],
    transfer_curation_team: ['MsgTransferCurationTeam', 'core/transfer_curation_team', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['new_owner', 102, 'string']]],
    delete_curation_team: ['MsgDeleteCurationTeam', 'core/delete_curation_team', [['community', 100, 'string'], ['team_id', 101, 'uint']]],
    set_curation_preference: ['MsgSetCurationPreference', 'core/set_curation_preference', [['community', 100, 'string'], ['mode', 101, 'uint'], ['pinned_team_id', 102, 'uint']]],
    set_curation_post_hidden: ['MsgSetCurationPostHidden', 'core/set_curation_post_hidden', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['target', 102, 'string'], ['hidden', 103, 'bool']]],
    set_curation_user_hidden: ['MsgSetCurationUserHidden', 'core/set_curation_user_hidden', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['target', 102, 'string'], ['hidden', 103, 'bool']]],
    set_curation_thread_locked: ['MsgSetCurationThreadLocked', 'core/set_curation_thread_locked', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['root_hash', 102, 'string'], ['locked', 103, 'bool']]],
    set_curation_subscriber_only: ['MsgSetCurationSubscriberOnly', 'core/set_curation_subscriber_only', [['community', 100, 'string'], ['team_id', 101, 'uint'], ['enabled', 102, 'bool']]],
    claim_creator_rewards: ['MsgClaimCreatorRewards', 'core/claim_creator_rewards', [['epoch_ids', 100, 'repeated_uint']]],
});

// /pow/ is not fingerprinted the way /static/ is, so a bare worker URL is served
// from a browser's own cache for as long as the response allowed -- v1.38.1
// shipped a worker change no returning visitor would have received. The build
// version makes the URL change with every release.
const POW_WORKER_URL = `/pow/worker.js?v=${encodeURIComponent(
    typeof __MIRAGE_APP_VERSION__ === 'string' && __MIRAGE_APP_VERSION__ ? __MIRAGE_APP_VERSION__ : 'dev'
)}`;

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
    "empty target": "target_required",
    "empty reason": "reason_required",
    "Invalid recipient or amount": "invalid_recipient_or_amount",
    "Recipient must be a mirage1 address": "recipient_must_be_mirage1",
    "Minimum amount is 0.001 MIRAGE": "amount_too_small",
    "Missing target or award type": "award_missing_target_or_type",
    "Invalid level (must be 1 or 10)": "invalid_level",
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
    "Proof of work WASM blocked by Content-Security-Policy": "pow_wasm_csp_blocked",
    "client error": "client_error",
    "transaction failed": "transaction_failed",
    "insufficient balance": "insufficient_balance",
    "missing onboarding handoff seed": "missing_onboarding_handoff",
    "handoff owner mismatch": "handoff_owner_mismatch",
    "owner_mismatch": "owner_mismatch",
    "missing_entry_owner": "missing_entry_owner",
    "missing_seed": "missing_recovery_phrase",
    "pipeline_failure": "pipeline_failure",
    "session_reset": "tx_cancelled",
    "cancelled": "tx_cancelled",
};

function getLocalErrorCode(message) {
    const code = LOCAL_ERROR_CODE_BY_MESSAGE[message];
    if (!code) {
        throw new Error(`[tx] unmapped local error message: ${message}`);
    }
    return code;
}

function cancelResult(reason) {
    const r = String(reason || 'cancelled');
    return {
        success: false,
        cancelled: true,
        reason: r,
        error_code: LOCAL_ERROR_CODE_BY_MESSAGE[r] || 'tx_cancelled',
    };
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

function formatHashRate(rate) {
    if (!Number.isFinite(rate) || rate <= 0) return null;
    if (rate >= 1_000_000) return `${(rate / 1_000_000).toFixed(2)}M H/s`;
    if (rate >= 1_000) return `${(rate / 1_000).toFixed(1)}k H/s`;
    return `${Math.round(rate)} H/s`;
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

            // PoW totals across the current queue (used for the end-of-queue
            // average hash-rate notification).  Reset in processTransactions().
            this.totalPowIterations = 0;
            this.totalPowSeconds = 0;

            this.setWarnOnLeave = null;
            this.updatePost = null;
            this.getPost = null;
            this.txStatusCallback = null;

            this.pendingTx = [];
            this.txPollTimer = null;
            this.pendingPosts = new Map();

            this.lastOnchainBalanceUmirage = 0;
            this.reservedUmirage = 0;
            this.pendingFeeUmirage = 0;
            this._queueIdCounter = 0;
            this._activePowWorker = null;
            this._draining = false;

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

            // Curator actions stay visible across route changes until their queued tx resolves.
            this.pendingCuration = new Map();
            this._curationListeners = new Set();

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

    _nextQueueId() {
        this._queueIdCounter += 1;
        return `tx-${Date.now()}-${this._queueIdCounter}`;
    }

    _requireOwnerBinding(entry = null) {
        let seedPhrase = null;
        let signerSource = 'vault';

        if (entry && entry._signerSource === 'handoff') {
            const handoff = peekHandoffByPurpose(entry._handoffPurpose || 'create-user-signing');
            if (!handoff || !handoff.seed) {
                throw new Error('missing onboarding handoff seed');
            }
            seedPhrase = handoff.seed;
            signerSource = 'handoff';
            if (entry.owner && handoff.owner && entry.owner !== handoff.owner) {
                throw new Error('handoff owner mismatch');
            }
        } else {
            seedPhrase = seedVault.getSeed();
        }

        if (!seedPhrase) throw new Error('missing recovery phrase');
        const normalized = requireValidMnemonic(seedPhrase);
        const { publicKey } = deriveKeysFromSeed(normalized);
        if (!publicKey) throw new Error('invalid signer address');
        return {
            owner: publicKey,
            sessionGeneration: getSessionGeneration(),
            normalizedSeed: normalized,
            signerSource,
        };
    }

    _verifyOwnerBinding(entry, phase) {
        this._lastOwnerVerifyReason = null;
        if (!entry || !entry.owner) {
            this._lastOwnerVerifyReason = 'missing_entry_owner';
            console.debug('[tx] owner-verify-fail', { phase, reason: 'missing_entry_owner', queueId: entry?.queueId });
            this._drainQueue('missing_entry_owner');
            return false;
        }
        let binding;
        try {
            binding = this._requireOwnerBinding(entry);
        } catch (err) {
            const reason = String(err?.message || 'missing_seed');
            this._lastOwnerVerifyReason = reason;
            console.debug('[tx] owner-verify-fail', { phase, reason, queueId: entry.queueId });
            this._drainQueue(reason);
            return false;
        }
        if (entry.owner !== binding.owner || entry.sessionGeneration !== binding.sessionGeneration) {
            this._lastOwnerVerifyReason = 'owner_mismatch';
            console.debug('[tx] owner-verify-fail', {
                phase,
                reason: 'owner_mismatch',
                queueId: entry.queueId,
                entryOwner: entry.owner,
                currentOwner: binding.owner,
                entryGeneration: entry.sessionGeneration,
                currentGeneration: binding.sessionGeneration,
            });
            this._drainQueue('owner_mismatch');
            return false;
        }
        return true;
    }

    _getAvailableBalanceUmirage() {
        const stored = Math.max(0, Math.trunc(Number(Storage.load('user_balance', '0'))));
        const onChain = Math.max(0, Math.trunc(Number(this.lastOnchainBalanceUmirage || 0)));
        const base = Math.max(stored, onChain);
        const reserved = Math.max(0, Math.trunc(Number(this.reservedUmirage || 0)));
        return Math.max(0, base - reserved);
    }

    _applyReservation(entry) {
        const amount = Math.trunc(Number(entry._reserveUmirage || 0));
        if (amount <= 0) return;
        this.reservedUmirage = Math.max(0, Math.trunc(Number(this.reservedUmirage || 0)) + amount);
        this.pendingFeeUmirage = this.reservedUmirage;
        console.debug('[tx] reserve-balance', { queueId: entry.queueId, amount, reservedTotal: this.reservedUmirage });
    }

    _releaseEntryReservation(entry) {
        const amount = Math.trunc(Number(entry?._reserveUmirage || 0));
        if (amount <= 0 || entry._reservationReleased) return;
        entry._reservationReleased = true;
        this.reservedUmirage = Math.max(0, Math.trunc(Number(this.reservedUmirage || 0)) - amount);
        this.pendingFeeUmirage = this.reservedUmirage;
        console.debug('[tx] release-reservation', { queueId: entry.queueId, amount, reservedTotal: this.reservedUmirage });
    }

    _terminateActivePowWorker() {
        if (!this._activePowWorker) return;
        try {
            console.debug('[tx] terminate-pow-worker');
            this._activePowWorker.terminate();
        } catch (_) { /* noop */ }
        this._activePowWorker = null;
    }

    _clearPendingMaps() {
        this.pendingVotes.clear();
        this.pendingFollows.clear();
        this.pendingBlocks.clear();
        this.pendingSends.clear();
        this.pendingSubscribes.clear();
        this.pendingDeletes.clear();
        this.pendingCuration.clear();
        this._notifyVoteListeners();
        this._notifyFollowListeners();
        this._notifyBlockListeners();
        this._notifySendListeners();
        this._notifySubscribeListeners();
        this._notifyDeleteListeners();
        this._notifyCurationListeners();
    }

    _drainQueue(reason) {
        if (this._draining) return;
        this._draining = true;
        const cancelReason = String(reason || 'cancelled');
        const cancelled = cancelResult(cancelReason);
        const pendingCount = this.transactions.length;
        console.debug('[tx] drain-queue', { reason: cancelReason, pendingCount, error_code: cancelled.error_code });

        this._terminateActivePowWorker();

        for (const entry of this.transactions) {
            this._releaseEntryReservation(entry);
            if (typeof entry._resolve === 'function') {
                try { entry._resolve(cancelled); } catch (_) { /* noop */ }
            }
        }
        this.transactions = [];
        this.reservedUmirage = 0;
        this.pendingFeeUmirage = 0;
        this._clearPendingMaps();
        this.totalTransactions = 0;
        this.processedTransactions = 0;
        this.isProcessing = false;
        this._updateStatus('idle');
        if (this.setWarnOnLeave) {
            this.setWarnOnLeave(false);
        }
        this._draining = false;
    }

    cancelAll(reason = 'cancelled') {
        this._drainQueue(reason);
        return Promise.resolve();
    }

    resetSession(reason = 'session_reset') {
        this._drainQueue(reason);
        return Promise.resolve();
    }

    _stampQueueEntry(entry) {
        const binding = this._requireOwnerBinding(entry);
        entry.owner = binding.owner;
        entry.sessionGeneration = binding.sessionGeneration;
        entry.queueId = this._nextQueueId();
        entry._signerSource = entry._signerSource || binding.signerSource || 'vault';
        console.debug('[tx] stamp-queue-entry', {
            action: entry.action,
            queueId: entry.queueId,
            owner: entry.owner,
            sessionGeneration: entry.sessionGeneration,
            signerSource: entry._signerSource,
        });
        return entry;
    }

    _pushStampedTransaction(entry) {
        this._stampQueueEntry(entry);
        if (entry._reserveUmirage > 0) {
            this._applyReservation(entry);
        }
        this.transactions.push(entry);
        this.totalTransactions += 1;
        this.processTransactions();
    }

    _enqueueBoundTransaction(baseTx, options = {}) {
        const {
            reserveUmirage = 0,
            forcePow = false,
            beforeEnqueue,
            onResolve,
            extraKeys = {},
        } = options;

        if (reserveUmirage > 0) {
            const available = this._getAvailableBalanceUmirage();
            if (available < reserveUmirage) {
                const haveM = (available / 1000000).toFixed(3);
                const needM = (reserveUmirage / 1000000).toFixed(3);
                return Promise.resolve(this._fail("insufficient balance", { balance: haveM, needed: needM }));
            }
        }

        if (typeof beforeEnqueue === 'function') {
            const pre = beforeEnqueue();
            if (pre && pre.success === false) {
                return Promise.resolve(pre);
            }
        }

        return new Promise((resolve) => {
            const entry = {
                ...baseTx,
                ...extraKeys,
                _forcePow: forcePow,
            };
            if (reserveUmirage > 0) {
                entry._reserveUmirage = Math.trunc(reserveUmirage);
            }
            entry._resolve = (result) => {
                this._releaseEntryReservation(entry);
                if (typeof onResolve === 'function') {
                    try { onResolve(result); } catch (_) { /* noop */ }
                }
                resolve(result);
            };
            try {
                this._pushStampedTransaction(entry);
            } catch (err) {
                entry._resolve(this._failFromException(err));
            }
        });
    }

    _getSubscribeFeeUmirage(level, monthlyFeeUmirage) {
        const explicit = Math.trunc(Number(monthlyFeeUmirage) || 0);
        if (explicit > 0) return explicit;
        let cfg;
        try {
            cfg = JSON.parse(localStorage.getItem('chainConfig') || '');
        } catch (_) {
            throw new Error('chainConfig unavailable');
        }
        if (!cfg || typeof cfg !== 'object') throw new Error('chainConfig unavailable');
        const tiers = cfg.subscription_tiers || cfg.tiers;
        if (!Array.isArray(tiers)) throw new Error('subscription tiers unavailable');
        const targetLevel = Number(level);
        const tierIdx = targetLevel === 1 ? 1 : targetLevel === 10 ? 2 : -1;
        if (tierIdx < 0 || tierIdx >= tiers.length) throw new Error('Invalid level');
        const fee = Math.trunc(Number(tiers[tierIdx]?.period_fee || 0));
        if (fee <= 0) throw new Error('subscription fee unavailable');
        return fee;
    }

    _getAwardCostUmirage(awardType) {
        let cfg;
        try {
            cfg = JSON.parse(localStorage.getItem('chainConfig') || '');
        } catch (_) {
            throw new Error('chainConfig unavailable');
        }
        if (!cfg || typeof cfg !== 'object') throw new Error('chainConfig unavailable');
        const configs = cfg.award_configs;
        if (!Array.isArray(configs)) throw new Error('award configs unavailable');
        const type = String(awardType || '').trim();
        const match = configs.find((c) => c && c.name === type);
        const cost = Math.trunc(Number(match?.cost || 0));
        if (cost <= 0) throw new Error(`Unknown award type: ${type}`);
        return cost;
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

    addCurationListener(callback) {
        if (typeof callback === 'function') this._curationListeners.add(callback);
        return () => this._curationListeners.delete(callback);
    }

    _notifyCurationListeners() {
        const pending = this.getPendingCuration();
        this._curationListeners.forEach((callback) => {
            try { callback(pending); } catch (_) { /* noop */ }
        });
    }

    getPendingCuration() {
        return Object.fromEntries(this.pendingCuration);
    }

    _enqueueCuration(action, payload, community = '', teamId = 0, target = '') {
        const key = curationPendingKey(action, community, teamId, target);
        if (this.pendingCuration.has(key)) {
            return Promise.resolve({
                success: false,
                error_code: 'curation_action_pending',
                error: 'This curator action is already pending.',
            });
        }
        const queuePosition = this.totalTransactions + 1;
        console.debug('[curation] enqueue', { action, community, teamId, target, queuePosition });
        return this._enqueueBoundTransaction(
            { action, ...payload },
            {
                beforeEnqueue: () => {
                    this.pendingCuration.set(key, { action, community, teamId, target, queuePosition });
                    this._notifyCurationListeners();
                    return null;
                },
                onResolve: (result) => {
                    this.pendingCuration.delete(key);
                    this._notifyCurationListeners();
                    if (result?.success) invalidateCurationReads(community);
                    console.debug('[curation] resolved', { action, community, teamId, target, success: !!result?.success });
                },
            },
        );
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

                    // Sync post vote metadata after indexing for accurate display
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
                            let existing = this.getPost(tLower);
                            if (!existing) {
                                const exactKey = String(target).trim();
                                existing = this.getPost(exactKey);
                                if (existing) postKey = exactKey;
                            }
                            const serverDir = vote > 0 ? 1 : (vote < 0 ? -1 : 0);
                            if (existing) {
                                const updateData = {};
                                if (existing.direction !== serverDir) {
                                    updateData.direction = serverDir;
                                }
                                if (typeof details.target_points === 'number' && existing.points !== details.target_points) {
                                    updateData.points = details.target_points;
                                }
                                if (typeof weight === 'number' && existing.user_weight !== weight) {
                                    updateData.user_weight = weight;
                                }
                                if (Object.keys(updateData).length > 0) {
                                    console.debug('[TransactionHandler] vote indexed → sync post state', {
                                        target: postKey,
                                        update: updateData,
                                    });
                                    this.updatePost(postKey, updateData);
                                } else {
                                    console.debug('[TransactionHandler] vote indexed → post already synced', {
                                        target: postKey,
                                    });
                                }
                            }
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
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async createUser(usernameRaw) {
        try {
            const username = String(usernameRaw || "").trim();
            if (!username) return this._fail("empty username");

            // Prefer in-memory onboarding handoff so we never wipe an existing vault
            // before create_user confirms on-chain.
            const handoff = peekHandoffByPurpose('create-user-signing');
            if (!handoff || !handoff.seed) {
                return this._fail("missing onboarding handoff seed");
            }

            return this._enqueueBoundTransaction({
                action: 'set_username',
                username,
                _signerSource: 'handoff',
                _handoffPurpose: 'create-user-signing',
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async setUsername(usernameRaw) {
        try {
            const username = String(usernameRaw || "").trim();
            if (!username) return this._fail("empty username");

            return this._enqueueBoundTransaction({
                action: 'set_username',
                username,
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async setBiography(biographyRaw) {
        try {
            const biography = String(biographyRaw ?? "").trim();
            return this._enqueueBoundTransaction({
                action: 'set_biography',
                biography,
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async createCuratorTeam(community, name, description = '', policy = '') {
        try {
            const slug = requireCommunitySlug(community);
            const teamName = String(name || '').trim();
            if (!teamName) throw new Error('team name is required');
            return this._enqueueCuration('create_curation_team', {
                community: slug,
                name: teamName,
                description: String(description),
                policy: String(policy),
            }, slug);
        } catch (e) { return this._failFromException(e); }
    }

    async updateCurationTeam(community, teamId, name, description = '', policy = '') {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const teamName = String(name || '').trim();
            if (!teamName) throw new Error('team name is required');
            return this._enqueueCuration('set_curation_team_profile', {
                community: slug, team_id: id, name: teamName,
                description: String(description), policy: String(policy),
            }, slug, id);
        } catch (e) { return this._failFromException(e); }
    }

    async inviteCurationTeamMember(community, teamId, invitee) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(invitee || '').trim().toLowerCase();
            if (!target) throw new Error('invitee is required');
            return this._enqueueCuration('invite_curator', {
                community: slug, team_id: id, target,
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async revokeCurationTeamInvitation(community, teamId, invitee) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(invitee || '').trim().toLowerCase();
            if (!target) throw new Error('invitee is required');
            return this._enqueueCuration('revoke_curator_invite', {
                community: slug, team_id: id, target,
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async respondCurationTeamInvitation(community, teamId, accept) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(Storage.load('publicKey', '') || '').toLowerCase();
            const action = accept ? 'accept_curator_invite' : 'decline_curator_invite';
            return this._enqueueCuration(action, {
                community: slug, team_id: id,
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async removeCurationTeamMember(community, teamId, member) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(member || '').trim().toLowerCase();
            if (!target) throw new Error('member is required');
            return this._enqueueCuration('remove_curator', {
                community: slug, team_id: id, target,
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async leaveCurationTeam(community, teamId) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(Storage.load('publicKey', '') || '').toLowerCase();
            return this._enqueueCuration('leave_curation_team', {
                community: slug, team_id: id,
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async transferCurationTeamLeadership(community, teamId, newLeader) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(newLeader || '').trim().toLowerCase();
            if (!target) throw new Error('new leader is required');
            return this._enqueueCuration('transfer_curation_team', {
                community: slug, team_id: id, new_owner: target,
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async deleteCurationTeam(community, teamId) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            return this._enqueueCuration('delete_curation_team', {
                community: slug, team_id: id,
            }, slug, id);
        } catch (e) { return this._failFromException(e); }
    }

    async moderateCurationPost(community, teamId, postId, hidden) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(postId || '').trim().toLowerCase();
            if (!target) throw new Error('post id is required');
            return this._enqueueCuration('set_curation_post_hidden', {
                community: slug, team_id: id, target, hidden: Boolean(hidden),
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async moderateCurationUser(community, teamId, user, hidden) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(user || '').trim().toLowerCase();
            if (!target) throw new Error('user is required');
            return this._enqueueCuration('set_curation_user_hidden', {
                community: slug, team_id: id, target, hidden: Boolean(hidden),
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async setCurationThreadLocked(community, teamId, rootHash, locked) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            const target = String(rootHash || '').trim().toLowerCase();
            if (!target) throw new Error('root hash is required');
            return this._enqueueCuration('set_curation_thread_locked', {
                community: slug, team_id: id, root_hash: target, locked: Boolean(locked),
            }, slug, id, target);
        } catch (e) { return this._failFromException(e); }
    }

    async setCurationSubscriberOnly(community, teamId, enabled) {
        try {
            const slug = requireCommunitySlug(community);
            const id = requireTeamId(teamId);
            return this._enqueueCuration('set_curation_subscriber_only', {
                community: slug, team_id: id, enabled: Boolean(enabled),
            }, slug, id);
        } catch (e) { return this._failFromException(e); }
    }

    async setCurationPreference(community, mode, pinnedTeamId = 0) {
        try {
            const slug = requireCommunitySlug(community);
            const selectedMode = Number(mode);
            if (![0, 1, 2].includes(selectedMode)) throw new Error('invalid curation mode');
            const teamId = selectedMode === 1 ? requireTeamId(pinnedTeamId) : 0;
            return this._enqueueCuration('set_curation_preference', {
                community: slug, mode: selectedMode, pinned_team_id: teamId,
            }, slug);
        } catch (e) { return this._failFromException(e); }
    }

    async claimCreatorRewards(epochIds) {
        try {
            const ids = [...new Set((epochIds || []).map(Number))].sort((a, b) => a - b);
            if (!ids.length || ids.length > 30 || ids.some((id) => !Number.isSafeInteger(id) || id <= 0)) {
                throw new Error('invalid epoch ids');
            }
            const owner = String(Storage.load('publicKey', '') || '').toLowerCase();
            return this._enqueueCuration('claim_creator_rewards', { epoch_ids: ids }, '', 0, owner);
        } catch (e) { return this._failFromException(e); }
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
                this._pushStampedTransaction(transaction);
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
                this._pushStampedTransaction(transaction);
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
                this._pushStampedTransaction(transaction);
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
                this._pushStampedTransaction(transaction);
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async blockTopic(topic) {
        try {
            const publicKey = Storage.load("publicKey", "");
            const community = String(topic || "").trim().toLowerCase();
            if (!community) return this._fail("empty community");
            if (!publicKey) return this._fail("Not logged in");

            // Check if community is already blocked
            try {
                const blocked = await Api.get('get_user_blocked', { address: publicKey }, { timeoutMs: 5000 });
                const blockedCommunities = (blocked?.blocked_communities || []).map(t => String(t).toLowerCase());
                if (blockedCommunities.includes(community)) {
                    return this._fail("community is already blocked");
                }
            } catch (_) { }

            const key = `topic:${community}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("block topic already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'block', type: 'topic', target: community, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue block_community", { community, target: publicKey, queuePosition });

            const baseTx = {
                action: 'block_community',
                community,
                topic: community,
                target: publicKey,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    // Mutual exclusion: blocking a community leaves it on-chain.
                    // Update sidebar immediately so the blocked community disappears.
                    if (result?.success) {
                        // Delay all feed/sidebar updates so the caller can show success UI first
                        setTimeout(() => {
                            notifyTopicsUpdated({ removed: community });
                            invalidateSubCache();
                            window.dispatchEvent(new CustomEvent('topicBlocked', { detail: { topic: community } }));
                        }, 3200);
                    }
                    console.debug("[blocks] resolved block_community", { community, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this._pushStampedTransaction(transaction);
            });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    async unblockTopic(topic) {
        try {
            const publicKey = Storage.load("publicKey", "");
            const community = String(topic || "").trim().toLowerCase();
            if (!community) return this._fail("empty community");
            if (!publicKey) return this._fail("Not logged in");
            const key = `topic:${community}`;
            if (this.pendingBlocks.has(key)) {
                return this._fail("unblock topic already in progress");
            }

            const queuePosition = this.totalTransactions + 1;
            this.pendingBlocks.set(key, { action: 'unblock', type: 'topic', target: community, queuePosition });
            this._notifyBlockListeners();
            console.debug("[blocks] enqueue unblock_community", { community, target: publicKey, queuePosition });

            const baseTx = {
                action: 'unblock_community',
                community,
                topic: community,
                target: publicKey,
            };

            return new Promise((resolve) => {
                const wrappedResolve = (result) => {
                    this.pendingBlocks.delete(key);
                    this._notifyBlockListeners();
                    if (result?.success) {
                        window.dispatchEvent(new CustomEvent('topicUnblocked', { detail: { topic: community } }));
                    }
                    console.debug("[blocks] resolved unblock_community", { community, success: !!result?.success, error: result?.error });
                    resolve(result);
                };
                const transaction = { ...baseTx, _resolve: wrappedResolve, _blockKey: key };
                this._pushStampedTransaction(transaction);
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
            this._pushStampedTransaction(transaction);
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
            this._pushStampedTransaction(transaction);
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
            action: 'join_community',
            userId: publicKey,
            community: topicTrimmed,
            topic: topicTrimmed,
        };

        return new Promise((resolve) => {
            const wrappedResolve = (result) => {
                this.pendingFollows.delete(key);
                this._notifyFollowListeners();
                resolve(result);
            };
            const transaction = { ...baseTx, _resolve: wrappedResolve, _followKey: key };
            this._pushStampedTransaction(transaction);
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
            action: 'leave_community',
            userId: publicKey,
            community: topicTrimmed,
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
            this._pushStampedTransaction(transaction);
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
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            const why = String(reason || "").trim();
            if (!txhashTrimmed) return this._fail("empty target");
            if (!why) return this._fail("empty reason");

            return this._enqueueBoundTransaction({
                action: 'report',
                target: txhashTrimmed,
                reason: why,
            }, { forcePow: true });
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
            const targetTrimmed = String(targetAddress || "").trim().toLowerCase();

            if (!targetTrimmed || !amountMirage || amountMirage <= 0) {
                return this._fail("Invalid recipient or amount");
            }

            if (!targetTrimmed.startsWith("mirage1")) {
                return this._fail("Recipient must be a mirage1 address");
            }

            const amountUmirage = Math.floor(amountMirage * 1000000);
            if (amountUmirage < 1000) {
                return this._fail("Minimum amount is 0.001 MIRAGE");
            }

            updateNotification("Sending tokens");

            const sendKey = `send:${targetTrimmed}`;
            return this._enqueueBoundTransaction({
                action: 'send_tokens',
                target: targetTrimmed,
                amount: amountUmirage,
            }, {
                reserveUmirage: amountUmirage,
                beforeEnqueue: () => {
                    if (this.pendingSends.has(sendKey)) {
                        return this._fail("send tokens already in progress");
                    }
                    const queuePosition = this.totalTransactions + 1;
                    this.pendingSends.set(sendKey, { target: targetTrimmed, amount: amountUmirage, queuePosition });
                    this._notifySendListeners();
                    console.debug("[send_tokens] enqueue", { target: targetTrimmed, amount: amountUmirage, queuePosition });
                    return null;
                },
                onResolve: () => {
                    this.pendingSends.delete(sendKey);
                    this._notifySendListeners();
                },
            }).then((result) => {
                console.debug("[send_tokens] resolved", {
                    target: targetTrimmed,
                    success: !!result?.success,
                    error: result?.error,
                });
                return result;
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
            const target = String(targetPostId || "").trim().toLowerCase();
            const type = String(awardType || "").trim();

            if (!target || !type) {
                return this._fail("Missing target or award type");
            }

            updateNotification("Giving award");
            const awardCost = this._getAwardCostUmirage(type);
            console.debug('[TransactionHandler] giveAward.enqueue', { target, award_type: type, awardCost });

            return this._enqueueBoundTransaction({
                action: 'award',
                target,
                award_type: type,
            }, { reserveUmirage: awardCost });
        } catch (e) {
            return this._failFromException(e);
        }
    }

    /**
     * Subscribe (or gift a subscription) to a tier level.
     * @param {number} level - Target paid subscription level (1=Subscriber, 10=Agent)
     * @param {number} monthlyFeeUmirage - The monthly fee in umirage for the target tier
     * @param {string} [target] - Optional target address to gift the subscription to
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string, result?: any}>}
     */
    async subscribe(level, monthlyFeeUmirage, target) {
        try {
            const targetLevel = Number(level);

            if (targetLevel !== 1) {
                return this._fail("Invalid level (must be 1)");
            }

            const targetTrimmed = String(target || "").trim().toLowerCase();
            updateNotification(targetTrimmed ? "Gifting subscription" : "Subscribing");

            const feeUmirage = this._getSubscribeFeeUmirage(targetLevel, monthlyFeeUmirage);
            const binding = this._requireOwnerBinding();
            const recipient = targetTrimmed || String(binding.owner || "").trim().toLowerCase();
            const subKey = `subscribe:${recipient}`;

            return this._enqueueBoundTransaction({
                action: 'subscribe',
                level: targetLevel,
                target: targetTrimmed,
                period_count: 1,
            }, {
                reserveUmirage: feeUmirage,
                beforeEnqueue: () => {
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
                    return null;
                },
                onResolve: () => {
                    this.pendingSubscribes.delete(subKey);
                    this._notifySubscribeListeners();
                    console.debug("[subscribe] resolved", { target: recipient });
                },
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
            return this._enqueueBoundTransaction({
                action: 'set_auto_renewal',
                auto_renew: Boolean(autoRenew),
            });
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
            const binding = this._requireOwnerBinding();
            const target = String(binding.owner || "").trim().toLowerCase();
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
                this._pushStampedTransaction(transaction);
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
            const txhashTrimmed = String(txhash || "").trim().toLowerCase();
            if (!txhashTrimmed) return this._fail("empty txhash");

            updateNotification("Deleting post");
            return this._enqueueBoundTransaction({
                action: 'delete_post',
                target: txhashTrimmed,
            });
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
            const overrideLower = String(overrideId || "").trim().toLowerCase();
            if (!overrideLower || overrideLower.length !== 64) return this._fail("invalid override");
            const content = String(changes?.content || "").trim();
            const title = String(changes?.title || "").trim();
            const topic = String(changes?.topic || "").trim();
            const target = String(changes?.target || "").trim();
            const tagRaw = String(changes?.tag || "").trim().toLowerCase();
            const media = Array.isArray(changes?.media) ? changes.media : [];
            if (!ALLOWED_TAGS.has(tagRaw)) return this._fail("invalid tag");

            return this._enqueueBoundTransaction({
                action: 'edit_post',
                override: overrideLower,
                target,
                topic,
                title,
                content,
                tag: tagRaw,
                media,
            });
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
        const balanceVal = data.balance !== undefined ? data.balance : data.user_balance;
        if (balanceVal !== undefined) {
            this._persistUserBalance(balanceVal);
        }
        if (Object.prototype.hasOwnProperty.call(data, 'daily_quota')) Storage.save('daily_quota', data.daily_quota);
        if (Object.prototype.hasOwnProperty.call(data, 'renewal_warning')) Storage.save('renewal_warning', data.renewal_warning);
        console.debug('[TransactionHandler] cacheUserStatus', {
            hasUsername: data.username !== undefined,
            userLevel: data.user_level ?? null,
            hasBalance: balanceVal !== undefined,
            hasDailyQuota: Object.prototype.hasOwnProperty.call(data, 'daily_quota') && data.daily_quota !== null,
            hasRenewalWarning: Object.prototype.hasOwnProperty.call(data, 'renewal_warning') && data.renewal_warning !== null,
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
            this._pushStampedTransaction(transaction);
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

        this._pushStampedTransaction(transaction);
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
            const publicKey = Storage.load("publicKey", "");
            const seedPhrase = seedVault.getSeed() || "";
            if (!publicKey || !seedPhrase) {
                return this._fail("Not logged in");
            }

            const cleanTag = typeof tag === 'string' ? tag.trim().toLowerCase() : "";
            if (!ALLOWED_TAGS.has(cleanTag)) {
                return this._fail("invalid tag");
            }

            return this._enqueueBoundTransaction({
                action: 'create_post',
                userId: publicKey,
                topic,
                title,
                content,
                tag: cleanTag,
                media: Array.isArray(media) ? media : [],
            });
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

        this._pushStampedTransaction(transaction);
    }

    /**
     * Create a comment and wait for completion (PoW + broadcast)
     * @param {string} parentId - txhash of parent post/comment
     * @param {string} content
     * @returns {Promise<{success: boolean, error?: string, tx_hash?: string}>}
     */
    async createCommentAsync(parentId, content) {
        try {
            const publicKey = Storage.load("publicKey", "");
            const seedPhrase = seedVault.getSeed() || "";
            if (!publicKey || !seedPhrase) {
                return this._fail("Not logged in");
            }

            return this._enqueueBoundTransaction({
                action: 'create_comment',
                userId: publicKey,
                parentId,
                content,
            });
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
        this.totalPowIterations = 0;
        this.totalPowSeconds = 0;

        let hadFailure = false;
        let hadQuestAction = false; // Track if any quest-relevant actions were processed
        while (this.transactions.length > 0) {
            const queuedPeek = this.transactions[0];
            if (!queuedPeek) break;
            if (!this._verifyOwnerBinding(queuedPeek, 'dequeue')) {
                hadFailure = true;
                break;
            }
            const queued = this.transactions.shift();
            const _resolve = typeof queued._resolve === 'function' ? queued._resolve : null;
            const forcePow = queued._forcePow === true;
            const {
                _resolve: _ignored,
                _followKey: _ignored2,
                _blockKey: _ignored3,
                _deleteKey: _ignored4,
                _voteKey: _ignored6,
                _sendKey: _ignored7,
                _forcePow: _ignored8,
                _reserveUmirage: _ignored9,
                owner: _ignored10,
                sessionGeneration: _ignored11,
                queueId: _ignored12,
                _signerSource: _ignored13,
                _handoffPurpose: _ignored14,
                ...transaction
            } = queued;
            const giftTarget = String(transaction.target || '').trim();
            const _isGiftSubscribe = transaction.action === 'subscribe' && giftTarget !== ''; // eslint-disable-line no-unused-vars
            this.processedTransactions += 1;
            // Track quest-relevant actions
            if (transaction.action === 'create_vote' || transaction.action === 'create_post' || transaction.action === 'create_comment') {
                hadQuestAction = true;
            }

            const failAndDrain = (failResult) => {
                this._releaseEntryReservation(queued);
                if (_resolve) _resolve(failResult);
                this._drainQueue('pipeline_failure');
                hadFailure = true;
            };

            let last_block_hash = "";
            let pow_difficulty = 0;
            let pow_base_bits_relay = 0;
            let pow_factor_relay = 0;
            const userLevelNow = Number(Storage.load('user_level', '0')) || 0;
            const NO_POW_QUEUE_ACTIONS = new Set(['subscribe', 'set_auto_renewal', 'award']);
            if (userLevelNow === 0 && !NO_POW_QUEUE_ACTIONS.has(transaction.action)) {
                try {
                    const addrNow = queued.owner || Storage.load('publicKey', '');
                    const status = await Api.get('get_parameters', addrNow ? { address: addrNow } : undefined);
                    last_block_hash = status.last_block_hash || "";
                    pow_difficulty = requirePowDifficulty(status.pow_difficulty);
                    pow_base_bits_relay = requirePowBaseBits(status.pow_base_bits);
                    pow_factor_relay = requirePowFactor(status.pow_factor);
                    const onChainBalance = Math.max(0, Math.trunc(Number(typeof status.balance !== 'undefined' ? status.balance : Storage.load('user_balance', '0'))));
                    const prevOnChain = this.lastOnchainBalanceUmirage;
                    this.lastOnchainBalanceUmirage = onChainBalance;
                    if (this.reservedUmirage > 0) {
                        const spentIncluded = onChainBalance <= Math.max(0, prevOnChain - this.reservedUmirage);
                        if (spentIncluded) {
                            this.reservedUmirage = 0;
                            this.pendingFeeUmirage = 0;
                        }
                    }
                    const effectiveBalance = Math.max(0, this.lastOnchainBalanceUmirage - Math.max(0, this.reservedUmirage));
                    this._persistUserBalance(effectiveBalance, { normalizeStorage: true, updateLastOnchain: false });
                } catch (error) {
                    const msg = (error && error.message) ? error.message : 'network error';
                    failAndDrain(this._fail("transaction failed", { details: msg }));
                    break;
                }
            } else {
                // Subscribers and fee-only actions: no PoW params fetch
                last_block_hash = NO_POW_QUEUE_ACTIONS.has(transaction.action) ? "" : Date.now().toString(16).padStart(64, '0');
                pow_difficulty = 0;
            }

            let final_transaction = undefined;
            let challenge = undefined;
            let derivedAddress;
            let privateKey;
            try {
                const binding = this._requireOwnerBinding(queued);
                derivedAddress = binding.owner;
                privateKey = derivePrivateKeyFromSeed(binding.normalizedSeed);
            } catch (err) {
                failAndDrain(this._failFromException(err));
                break;
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
            else if (transaction.action === "follow_topic" || transaction.action === "join_community") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: 'join_community',
                    community: (transaction.community || transaction.topic || "").toLowerCase(),
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (CURATION_TX_SPECS[transaction.action]) {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                const spec = CURATION_TX_SPECS[transaction.action];
                final_transaction = {
                    action: transaction.action,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
                for (const [fieldName] of spec[2]) {
                    final_transaction[fieldName] = transaction[fieldName];
                }
            }
            else if (transaction.action === "unfollow_topic" || transaction.action === "leave_community") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: 'leave_community',
                    community: (transaction.community || transaction.topic || "").toLowerCase(),
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
            else if (transaction.action === "block_topic" || transaction.action === "unblock_topic"
                || transaction.action === "block_community" || transaction.action === "unblock_community") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                const community = (transaction.community || transaction.topic || "").toLowerCase();
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target || "",
                    community,
                    topic: community,
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
            else if (transaction.action === "delete_post") {
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
            else if (transaction.action === "edit_post") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    override: transaction.override,
                    target: transaction.target || "",
                    topic: transaction.topic || "",
                    title: transaction.title || "",
                    content: transaction.content || "",
                    tag: transaction.tag || "",
                    media: Array.isArray(transaction.media) ? transaction.media : [],
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "report") {
                challenge = `${derivedAddress}:${last_block_hash}:${pow_difficulty}`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target,
                    reason: transaction.reason,
                    last_block_hash,
                    pow_difficulty: Number(pow_difficulty),
                    pow_base_bits: pow_base_bits_relay,
                    pow_factor: pow_factor_relay,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "subscribe") {
                challenge = `${derivedAddress}:${last_block_hash}:0`;
                final_transaction = {
                    action: transaction.action,
                    level: Number(transaction.level),
                    target: transaction.target || "",
                    period_count: Math.max(1, Number(transaction.period_count || 1) || 1),
                    last_block_hash: "",
                    pow_difficulty: 0,
                    pow_base_bits: 0,
                    pow_factor: 0,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "set_auto_renewal") {
                challenge = `${derivedAddress}:${last_block_hash}:0`;
                final_transaction = {
                    action: transaction.action,
                    auto_renew: Boolean(transaction.auto_renew),
                    last_block_hash: "",
                    pow_difficulty: 0,
                    pow_base_bits: 0,
                    pow_factor: 0,
                    timestamp: txTimestamp,
                };
            }
            else if (transaction.action === "award") {
                challenge = `${derivedAddress}:${last_block_hash}:0`;
                final_transaction = {
                    action: transaction.action,
                    target: transaction.target,
                    award_type: transaction.award_type,
                    last_block_hash: "",
                    pow_difficulty: 0,
                    pow_base_bits: 0,
                    pow_factor: 0,
                    timestamp: txTimestamp,
                };
            }

            if (final_transaction) {
                final_transaction.owner = queued.owner;
                final_transaction.sessionGeneration = queued.sessionGeneration;
                final_transaction.queueId = queued.queueId;
                final_transaction._forcePow = forcePow;
                // performTransaction re-verifies owner on `transaction`; handoff create_user
                // must keep signer source or sign-time verify reads the (empty) vault instead.
                if (queued._signerSource) final_transaction._signerSource = queued._signerSource;
                if (queued._handoffPurpose) final_transaction._handoffPurpose = queued._handoffPurpose;
                try {
                    console.debug('[tx] final-tx-signer-meta', {
                        action: final_transaction.action,
                        queueId: final_transaction.queueId,
                        signerSource: final_transaction._signerSource || 'vault',
                        handoffPurpose: final_transaction._handoffPurpose || null,
                    });
                } catch (_) { /* noop */ }
            }

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
                    if (!this._verifyOwnerBinding(queued, 'pre-sign')) {
                        failAndDrain(cancelResult(this._lastOwnerVerifyReason || 'owner_mismatch'));
                        break;
                    }
                    result = await this.performTransaction(final_transaction, challenge, privateKey, derivedAddress, forcePow);
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
                failAndDrain(this._fail("transaction failed", cleanMsg ? { details: cleanMsg } : undefined));
                break;
            }
            if (!result || !result.success) {
                if (result && result.cancelled) {
                    failAndDrain(result);
                    break;
                }
                if (result && result.error_code) {
                    failAndDrain(result);
                } else {
                    const msg = String(result && result.error ? result.error : 'Transaction failed');
                    failAndDrain(this._fail("transaction failed", msg ? { details: msg } : undefined));
                }
                break;
            }

            this._releaseEntryReservation(queued);
            if (_resolve) _resolve(result);

        }

        if (!hadFailure) {
            // Show a single end-of-queue notification. For multi-tx queues, report
            // the average PoW hash rate across the queue rather than firing a toast
            // after every individual tx.
            const userLevel = Number(Storage.load('user_level', '0')) || 0;
            const totalElapsed = (Date.now() - this.startTime) / 1000;
            const totalPowSec = this.totalPowSeconds || 0;
            const totalPowIter = this.totalPowIterations || 0;
            const avgRate = totalPowSec > 0.05 ? formatHashRate(totalPowIter / totalPowSec) : null;
            if (this.totalTransactions > 1) {
                if (userLevel >= 1) {
                    updateNotification("All transactions submitted");
                } else {
                    updateNotification(avgRate
                        ? `All transactions submitted (avg ${avgRate})`
                        : "All transactions submitted");
                }
            } else {
                if (userLevel >= 1) {
                    updateNotification("Transaction submitted");
                } else {
                    updateNotification(`Transaction submitted (took ${totalElapsed.toFixed(1)}s)`);
                }
            }
            // Dispatch event for quest-relevant actions so quest progress can refresh
            if (hadQuestAction) {
                window.dispatchEvent(new CustomEvent('questActionCompleted', { detail: { batch: true } }));
            }
        } else {
            // Replace the pinned "Processing tx N/M" toast so it doesn't sit
            // there forever when the queue aborts mid-flight.  Callers may
            // also surface their own per-action error UI; this is a safety
            // net for the toast.
            updateNotification("Transaction failed", 5.0, true);
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
    canonicalPost({ pub_bytes, last_block_hash, difficulty, proof, timestamp, target, topic, community, title, content, tag, media, nonce, protocol_version }) {
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
            tag101, encStr(community || topic || ""),
            tag102, encStr(title || ""),
            tag103, encStr(content || ""),
            tag104, encStr(tag || ""),
        ];
        // Encode repeated media field (tag 105)
        for (const m of (media || [])) {
            parts.push(tag105);
            parts.push(encStr(m));
        }
        parts.push(Uint8Array.from([106]));
        parts.push(uvarint((protocol_version == null ? 1 : protocol_version) >>> 0));
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

    // Build canonical bytes for MsgJoinCommunity (community at tag 100, no target)
    canonicalJoinCommunity({ pub_bytes, last_block_hash, difficulty, proof, timestamp, community, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgJoinCommunity\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);
        const tag100 = Uint8Array.from([100]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(community || ""),
        );
    }

    canonicalCuration(action, values) {
        const spec = CURATION_TX_SPECS[action];
        if (!spec) throw new Error(`Unknown curator action: ${action}`);
        const fields = [];
        for (const [fieldName, tag, type] of spec[2]) {
            const value = values[fieldName];
            if (type === 'repeated_uint') {
                for (const item of value || []) fields.push([tag, uvarint64(item)]);
            } else if (type === 'string') {
                fields.push([tag, encStr(value || '')]);
            } else if (type === 'uint') {
                fields.push([tag, uvarint64(value || 0)]);
            } else if (type === 'bool') {
                fields.push([tag, Uint8Array.from([value ? 1 : 0])]);
            } else {
                throw new Error(`Unknown canonical field type: ${type}`);
            }
        }
        return buildCanonical({
            msgType: spec[0],
            pub_bytes: values.pub_bytes,
            last_block_hash: values.last_block_hash,
            difficulty: values.difficulty,
            proof: values.proof,
            timestamp: values.timestamp,
            nonce: values.nonce,
            fields,
        });
    }

    canonicalLeaveCommunity({ pub_bytes, last_block_hash, difficulty, proof, timestamp, community, nonce }) {
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgLeaveCommunity\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);
        const tag100 = Uint8Array.from([100]);
        return concat(
            prefix,
            tag2, encBytes(pub_bytes || new Uint8Array()),
            tag3, encBytes(hexToBytes(last_block_hash)),
            tag4, uvarint(difficulty >>> 0),
            tag5, uvarint(proof >>> 0),
            tag6, uvarint64(timestamp || 0),
            Uint8Array.from([7]), uvarint64(nonce),
            tag100, encStr(community || ""),
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockCommunity\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]); // community
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

    // Build canonical bytes for MsgUnblockCommunity (legacy helper name)
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
        const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockCommunity\x00");
        const tag2 = Uint8Array.from([2]);
        const tag3 = Uint8Array.from([3]);
        const tag4 = Uint8Array.from([4]);
        const tag5 = Uint8Array.from([5]);
        const tag6 = Uint8Array.from([6]);    // envelope_timestamp
        const tag100 = Uint8Array.from([100]);
        const tag101 = Uint8Array.from([101]); // community
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
        if (transaction?.owner && !this._verifyOwnerBinding(transaction, 'sign')) {
            resolve(cancelResult(this._lastOwnerVerifyReason || 'owner_mismatch'));
            return;
        }

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
            if (CURATION_TX_SPECS[action]) msgName = CURATION_TX_SPECS[action][0];
            else if (action === 'create_vote') msgName = 'MsgVote';
            else if (action === 'create_post' || action === 'create_comment') msgName = 'MsgPost';
            else if (action === 'follow_user') msgName = 'MsgFollowUser';
            else if (action === 'unfollow_user') msgName = 'MsgUnfollowUser';
            else if (action === 'follow_topic' || action === 'join_community') msgName = 'MsgJoinCommunity';
            else if (action === 'unfollow_topic' || action === 'leave_community') msgName = 'MsgLeaveCommunity';
            else if (action === 'block_post') msgName = 'MsgBlockPost';
            else if (action === 'unblock_post') msgName = 'MsgUnblockPost';
            else if (action === 'block_user') msgName = 'MsgBlockUser';
            else if (action === 'unblock_user') msgName = 'MsgUnblockUser';
            else if (action === 'block_topic' || action === 'block_community') msgName = 'MsgBlockCommunity';
            else if (action === 'unblock_topic' || action === 'unblock_community') msgName = 'MsgUnblockCommunity';
            else if (action === 'delete_post') msgName = 'MsgDelete';
            else if (action === 'delete_user') msgName = 'MsgDeleteUser';
            else if (action === 'send_tokens') msgName = 'MsgSendTokens';
            else if (action === 'set_username') msgName = 'MsgSetUsername';
            else if (action === 'set_biography') msgName = 'MsgSetBiography';
            else if (action === 'report') msgName = 'MsgReport';
            else if (action === 'edit_post') msgName = 'MsgEdit';
            else if (action === 'subscribe') msgName = 'MsgSubscribe';
            else if (action === 'set_auto_renewal') msgName = 'MsgSetAutoRenewal';
            else if (action === 'award') msgName = 'MsgAward';
            else throw new Error(`CRITICAL: Missing or invalid transaction.action: "${action}". Transaction must have explicit action field.`);

            let endpoint = '';
            if (CURATION_TX_SPECS[action]) {
                const difficulty = resolveTxDifficulty(transaction);
                const spec = CURATION_TX_SPECS[action];
                const canon = this.canonicalCuration(action, {
                    ...transaction,
                    pub_bytes: pubBytes,
                    difficulty,
                    proof: Number(proof),
                    nonce: envelopeNonce,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigB64 = btoa(Array.from(sigCompact.toFixedLength()).map((b) => String.fromCharCode(b)).join(''));
                toRelay = {
                    pubkey: pubB64,
                    signature: sigB64,
                    timestamp: transaction.timestamp,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                for (const [fieldName] of spec[2]) toRelay[fieldName] = transaction[fieldName];
                endpoint = spec[1];
            } else if (msgName === 'MsgSetUsername') {
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
            } else if (msgName === 'MsgJoinCommunity') {
                const difficulty = resolveTxDifficulty(transaction);
                const communityLower = (transaction.community || transaction.topic || "").toLowerCase();
                const canon = this.canonicalJoinCommunity({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    community: communityLower,
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
                    community: communityLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/join_community';
            } else if (msgName === 'MsgLeaveCommunity') {
                const difficulty = resolveTxDifficulty(transaction);
                const communityLower = (transaction.community || transaction.topic || "").toLowerCase();
                const canon = this.canonicalLeaveCommunity({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    community: communityLower,
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
                    community: communityLower,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/leave_community';
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
            } else if (msgName === 'MsgBlockCommunity') {
                const difficulty = resolveTxDifficulty(transaction);
                const community = (transaction.community || transaction.topic || "").toLowerCase();
                const targetAddr = (transaction.target || "").toLowerCase();
                const canon = this.canonicalBlockTopic({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetAddr,
                    topic: community,
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
                    target: targetAddr,
                    community,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/block_community';
            } else if (msgName === 'MsgUnblockCommunity') {
                const difficulty = resolveTxDifficulty(transaction);
                const community = (transaction.community || transaction.topic || "").toLowerCase();
                const targetAddr = (transaction.target || "").toLowerCase();
                const canon = this.canonicalUnblockTopic({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: difficulty,
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: targetAddr,
                    topic: community,
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
                    target: targetAddr,
                    community,
                    last_block_hash: transaction.last_block_hash,
                    pow_difficulty: difficulty,
                    pow: Number(proof),
                    envelope_nonce: envelopeNonce,
                };
                endpoint = 'core/unblock_community';
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
                const topic = transaction.community || transaction.topic || "";
                const mediaArr = Array.isArray(transaction.media) ? transaction.media : [];
                const canon = this.canonicalPost({
                    pub_bytes: pubBytes,
                    last_block_hash: transaction.last_block_hash,
                    difficulty: resolveTxDifficulty(transaction),
                    proof: Number(proof),
                    timestamp: transaction.timestamp,
                    target: transaction.target || "",
                    community: topic,
                    topic: topic,
                    title: transaction.title || "",
                    content: transaction.content || "",
                    tag: transaction.tag || "",
                    media: mediaArr,
                    nonce: envelopeNonce,
                    protocol_version: 1,
                });
                const digest = __CosmSha256(canon);
                const sigCompact = await __CosmSecp256k1.createSignature(digest, privBytes);
                const sigFixed = sigCompact.toFixedLength();
                const sigB64 = btoa(Array.from(sigFixed).map(b => String.fromCharCode(b)).join(''));
                toRelay = {
                    ...toRelay,
                    signature: sigB64,
                    topic: topic,
                    community: topic,
                    protocol_version: 1,
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
                const tag102 = Uint8Array.from([102]); // period_count
                const targetLevel = Number(transaction.level || 0);
                const periodCount = Math.max(1, Number(transaction.period_count || 1) || 1);
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
                canonParts.push(tag102, uvarint(periodCount));
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
                    period_count: periodCount,
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
                                            // No previous count: use in-memory root if present.
                                            try {
                                                const rootPost = this.getPost ? this.getPost(rootId) : null;
                                                if (rootPost && typeof rootPost.comments === 'number') {
                                                    Storage.setLastVisitCommentCount(rootId, rootPost.comments + 1);
                                                }
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
                // Per-tx "Transaction submitted" toast is intentionally suppressed here.
                // processTransactions() shows a single summary notification (with the
                // average elapsed time across the queue) once the queue is fully drained.

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
        } catch (error) {
            console.error('Transaction error:', error);
            const errMsg = String(error && error.message ? error.message : error);
            const errStr = String(error);
            const fullErr = errMsg + ' ' + errStr;
            if (/pow_required/i.test(fullErr) || error?.error_code === 'pow_required') {
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

            const effectiveForcePow = forcePow || transaction?._forcePow === true;

            if (transaction?.owner && !this._verifyOwnerBinding(transaction, 'sign')) {
                wrapResolve(cancelResult(this._lastOwnerVerifyReason || 'owner_mismatch'));
                return;
            }

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
            const canSkipPow = !effectiveForcePow && (userLevel >= 1 || NO_POW_ACTIONS.has(transaction.action));

            // Inform UI that we are starting a transaction
            this._setStatus("preparing");

            if (canSkipPow) {
                // Skip PoW computation for subscribers (PoW fields ignored by backend/chain)
                if (transaction && typeof transaction === "object") {
                    transaction.pow_difficulty = 0;
                    transaction.difficulty = 0;
                    transaction.pow = 0;
                }
                updateNotification("Submitting transaction", this.transactions.length > 0 ? 0 : 0.5);
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
            const worker = new Worker(POW_WORKER_URL);
            this._activePowWorker = worker;

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

            if (CURATION_TX_SPECS[action]) {
                const spec = CURATION_TX_SPECS[action];
                const parts = [
                    new TextEncoder().encode(`mirage.core.v1:${spec[0]}\x00`),
                    Uint8Array.from([2]), encBytes(pubBytes),
                    Uint8Array.from([3]), encBytes(hexToBytes(transaction.last_block_hash)),
                    Uint8Array.from([4]), uvarint64(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                ];
                for (const [fieldName, tag, type] of spec[2]) {
                    const value = transaction[fieldName];
                    if (type === 'repeated_uint') {
                        for (const item of value || []) parts.push(Uint8Array.from([tag]), uvarint64(item));
                    } else if (type === 'string') {
                        parts.push(Uint8Array.from([tag]), encStr(value || ''));
                    } else if (type === 'uint') {
                        parts.push(Uint8Array.from([tag]), uvarint64(value || 0));
                    } else if (type === 'bool') {
                        parts.push(Uint8Array.from([tag]), Uint8Array.from([value ? 1 : 0]));
                    }
                }
                baseBytes = concat(...parts);
            } else if (action === 'create_vote') {
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
                const topic = transaction.community || transaction.topic || "";
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
                    Uint8Array.from([106]), uvarint(1),
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
            } else if (action === 'follow_topic' || action === 'join_community') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgJoinCommunity\x00");
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
                    tag100, encStr((transaction.community || transaction.topic || "").toLowerCase()),
                );
            } else if (action === 'unfollow_topic' || action === 'leave_community') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgLeaveCommunity\x00");
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
                    tag100, encStr((transaction.community || transaction.topic || "").toLowerCase()),
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
            } else if (action === 'block_topic' || action === 'block_community') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgBlockCommunity\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                const community = (transaction.community || transaction.topic || "").toLowerCase();
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(community),
                );
            } else if (action === 'unblock_topic' || action === 'unblock_community') {
                const prefix = new TextEncoder().encode("mirage.core.v1:MsgUnblockCommunity\x00");
                const tag2 = Uint8Array.from([2]);
                const tag3 = Uint8Array.from([3]);
                const tag4 = Uint8Array.from([4]);
                const tag100 = Uint8Array.from([100]);
                const tag101 = Uint8Array.from([101]);
                const community = (transaction.community || transaction.topic || "").toLowerCase();
                baseBytes = concat(
                    prefix,
                    tag2, encBytes(pubBytes),
                    tag3, encBytes(hexToBytes(transaction.last_block_hash)),
                    tag4, uvarint(difficulty),
                    tag6, uvarint64(transaction.timestamp || 0),
                    Uint8Array.from([7]), uvarint64(envelopeNonce),
                    tag100, encStr(transaction.target || ""),
                    tag101, encStr(community),
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
                throw new Error(`Unknown transaction action: "${action}"`);
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
                // While more txs are queued, pin the toast (timeout=0) so it doesn't
                // slide out between this tx finishing and the next one's PoW interval
                // taking over — the next tx updates the same toast in place.
                const tmo = this.transactions.length > 0 ? 0 : 0.5;
                if (this.totalTransactions === 0)
                    updateNotification(`Processing transaction (${taken.toFixed(1)}s)`, tmo);
                else
                    updateNotification(`Processing tx ${this.processedTransactions}/${this.totalTransactions} (${taken.toFixed(1)}s)`, tmo);
            }, 100); // Update every 100ms

            // 60-second timeout for PoW
            const powTimeoutId = setTimeout(() => {
                if (powTimedOut) return;
                powTimedOut = true;
                worker.terminate();
                this._activePowWorker = null;
                clearInterval(intervalId);
                if (this.setWarnOnLeave) {
                    this.setWarnOnLeave(false);
                }
                this._setStatus("idle");
                updateNotification("PoW took too long. Please try again.", 5.0, true);
                wrapResolve(this._fail("Proof of work took too long (>60s). Your device may be too slow, or the network difficulty is too high. Please try again later."));
            }, 60000);

            worker.onerror = (event) => {
                if (powTimedOut) return;
                powTimedOut = true;
                clearTimeout(powTimeoutId);
                clearInterval(intervalId);
                try { worker.terminate(); } catch (_) { /* already dead */ }
                this._activePowWorker = null;
                if (this.setWarnOnLeave) {
                    this.setWarnOnLeave(false);
                }
                this._setStatus("idle");
                const detail = String((event && event.message) || 'worker_onerror');
                console.error('[PoW] worker onerror', detail);
                updateNotification("PoW failed. Please try again.", 5.0, true);
                wrapResolve(this._fail("Proof of work failed", { details: detail }));
            };

            worker.onmessage = async function (e) {
                if (powTimedOut) return;
                clearTimeout(powTimeoutId);

                // Received PoW result from the worker
                worker.terminate();
                this._activePowWorker = null;

                // Clear the flag after PoW is done
                if (this.setWarnOnLeave) {
                    this.setWarnOnLeave(false);
                }

                // Stop the interval for updating notifications
                clearInterval(intervalId);

                const workerData = e ? e.data : null;
                if (workerData && typeof workerData === 'object' && workerData.error) {
                    try { console.error('[PoW] worker error', workerData); } catch (_) { }
                    if (workerData.error === 'wasm_csp_blocked') {
                        updateNotification("PoW engine blocked by this browser. Please try again.", 5.0, true);
                        wrapResolve(this._fail("Proof of work WASM blocked by Content-Security-Policy"));
                        return;
                    }
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
                this.totalPowIterations += iterations;
                this.totalPowSeconds += taken;
                if (rawProof !== proof) {
                    try {
                        console.warn('[PoW] proof overflow normalized', { rawProof, proof, start });
                    } catch (_) { }
                }
                this._setStatus("submitting");
                try {
                    await this.handleTransactionResult(proof, transaction, challenge, privateKeyHex, signerAddress, wrapResolve);
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
