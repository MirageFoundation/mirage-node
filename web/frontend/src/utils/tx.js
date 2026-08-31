// Lightweight facade that lazily loads the heavy TransactionHandler only on demand
import Storage from './Storage';

let handlerPromise = null;
let _chainConfigFetchClaimed = false;

function getHandler() {
    if (!handlerPromise) {
        handlerPromise = import('./TransactionHandler').then((m) => m.default);
    }
    return handlerPromise;
}

// Callback wiring
export async function setWarnOnLeaveCallback(fn) {
    const h = await getHandler();
    return h.setWarnOnLeaveCallback(fn);
}

export async function updatePostCallback(fn) {
    const h = await getHandler();
    return h.updatePostCallback(fn);
}

export async function getPostCallback(fn) {
    const h = await getHandler();
    return h.getPostCallback(fn);
}

export async function setTxStatusCallback(fn) {
    const h = await getHandler();
    return h.setTxStatusCallback(fn);
}

export async function addStatusListener(fn) {
    const h = await getHandler();
    return h.addStatusListener(fn);
}

export async function getQueueStatus() {
    const h = await getHandler();
    return h.getQueueStatus();
}

export async function getNextQueuePosition() {
    const h = await getHandler();
    return h.getNextQueuePosition();
}

// Vote tracking
export async function addVoteListener(fn) {
    const h = await getHandler();
    return h.addVoteListener(fn);
}

export async function getPendingVotes() {
    const h = await getHandler();
    return h.getPendingVotes();
}

export async function isPendingVote(postId) {
    const h = await getHandler();
    return h.isPendingVote(postId);
}

export async function getPendingVoteDirection(postId) {
    const h = await getHandler();
    return h.getPendingVoteDirection(postId);
}

// Follow tracking
export async function addFollowListener(fn) {
    const h = await getHandler();
    return h.addFollowListener(fn);
}

export async function getPendingFollows() {
    const h = await getHandler();
    return h.getPendingFollows();
}

export async function isPendingFollow(type, target) {
    const h = await getHandler();
    return h.isPendingFollow(type, target);
}

export async function getPendingFollowInfo(type, target) {
    const h = await getHandler();
    return h.getPendingFollowInfo(type, target);
}

// Block tracking
export async function addBlockListener(fn) {
    const h = await getHandler();
    return h.addBlockListener(fn);
}

export async function getPendingBlocks() {
    const h = await getHandler();
    return h.getPendingBlocks();
}

export async function isPendingBlock(type, target) {
    const h = await getHandler();
    return h.isPendingBlock(type, target);
}

export async function getPendingBlockInfo(type, target) {
    const h = await getHandler();
    return h.getPendingBlockInfo(type, target);
}

// Send tokens tracking
export async function addSendListener(fn) {
    const h = await getHandler();
    return h.addSendListener(fn);
}

export async function getPendingSends() {
    const h = await getHandler();
    return h.getPendingSends();
}

export async function isPendingSend(target) {
    const h = await getHandler();
    return h.isPendingSend(target);
}

export async function getPendingSendInfo(target) {
    const h = await getHandler();
    return h.getPendingSendInfo(target);
}

export async function addSubscribeListener(fn) {
    const h = await getHandler();
    return h.addSubscribeListener(fn);
}

export async function getPendingSubscribes() {
    const h = await getHandler();
    return h.getPendingSubscribes();
}

export async function isPendingSubscribe(target) {
    const h = await getHandler();
    return h.isPendingSubscribe(target);
}

export async function getPendingSubscribeInfo(target) {
    const h = await getHandler();
    return h.getPendingSubscribeInfo(target);
}

// Delete-account tracking
export async function addDeleteListener(fn) {
    const h = await getHandler();
    return h.addDeleteListener(fn);
}

export async function getPendingDeletes() {
    const h = await getHandler();
    return h.getPendingDeletes();
}

export async function addCurationListener(fn) {
    const h = await getHandler();
    return h.addCurationListener(fn);
}

export async function getPendingCuration() {
    const h = await getHandler();
    return h.getPendingCuration();
}

export function needsChainConfigRefresh() {
    if (_chainConfigFetchClaimed) return false;
    let stale = false;
    if (!localStorage.getItem('chainConfig')) {
        stale = true;
    } else {
        const cachedAt = parseInt(localStorage.getItem('chain_config_cached_at') || '0');
        stale = Date.now() - cachedAt > 4 * 3600 * 1000;
    }
    if (stale) _chainConfigFetchClaimed = true;
    return stale;
}

export async function cacheChainConfig(data) {
    _chainConfigFetchClaimed = false;
    const h = await getHandler();
    return h.cacheChainConfig(data);
}

// Release the in-flight claim without caching a config. Used by callers
// that fetched `get_chain_config` but got back a null/error result, so the
// next `needsChainConfigRefresh()` check can re-enter and retry instead of
// being permanently wedged on the claimed flag.
export function releaseChainConfigClaim() {
    _chainConfigFetchClaimed = false;
}

export async function cacheNodeConfig(data) {
    const h = await getHandler();
    return h.cacheNodeConfig(data);
}

export async function cacheUserStatus(data) {
    const h = await getHandler();
    return h.cacheUserStatus(data);
}

// Transactional actions
export async function createUser(username) {
    const h = await getHandler();
    return h.createUser(username);
}

export async function setUsername(username) {
    const h = await getHandler();
    return h.setUsername(username);
}

export async function setBiography(biography) {
    const h = await getHandler();
    return h.setBiography(biography);
}

export async function createCuratorTeam(community, name, description) {
    const h = await getHandler();
    return h.createCuratorTeam(community, name, description);
}

export async function updateCurationTeam(community, teamId, name, description) {
    const h = await getHandler();
    return h.updateCurationTeam(community, teamId, name, description);
}

export async function inviteCurationTeamMember(community, teamId, invitee) {
    const h = await getHandler();
    return h.inviteCurationTeamMember(community, teamId, invitee);
}

export async function revokeCurationTeamInvitation(community, teamId, invitee) {
    const h = await getHandler();
    return h.revokeCurationTeamInvitation(community, teamId, invitee);
}

export async function respondCurationTeamInvitation(community, teamId, accept) {
    const h = await getHandler();
    return h.respondCurationTeamInvitation(community, teamId, accept);
}

export async function removeCurationTeamMember(community, teamId, member) {
    const h = await getHandler();
    return h.removeCurationTeamMember(community, teamId, member);
}

export async function leaveCurationTeam(community, teamId) {
    const h = await getHandler();
    return h.leaveCurationTeam(community, teamId);
}

export async function transferCurationTeamLeadership(community, teamId, newLeader) {
    const h = await getHandler();
    return h.transferCurationTeamLeadership(community, teamId, newLeader);
}

export async function deleteCurationTeam(community, teamId) {
    const h = await getHandler();
    return h.deleteCurationTeam(community, teamId);
}

export async function moderateCurationPost(community, teamId, postId, hidden) {
    const h = await getHandler();
    return h.moderateCurationPost(community, teamId, postId, hidden);
}

export async function moderateCurationUser(community, teamId, user, hidden) {
    const h = await getHandler();
    return h.moderateCurationUser(community, teamId, user, hidden);
}

export async function setCurationThreadLocked(community, teamId, rootHash, locked) {
    const h = await getHandler();
    return h.setCurationThreadLocked(community, teamId, rootHash, locked);
}

export async function setCurationSubscriberOnly(community, teamId, enabled) {
    const h = await getHandler();
    return h.setCurationSubscriberOnly(community, teamId, enabled);
}

export async function setCurationTag(community, teamId, tag) {
    const h = await getHandler();
    return h.setCurationTag(community, teamId, tag);
}

export async function setCurationPostTag(community, teamId, postId, tag, clear) {
    const h = await getHandler();
    return h.setCurationPostTag(community, teamId, postId, tag, clear);
}

export async function setCurationPreference(community, mode, pinnedTeamId) {
    const h = await getHandler();
    return h.setCurationPreference(community, mode, pinnedTeamId);
}

export async function claimCreatorRewards(epochIds) {
    const h = await getHandler();
    return h.claimCreatorRewards(epochIds);
}

export async function createPost(topic, title, content, tag = "", media = []) {
    const h = await getHandler();
    return h.createPost(topic, title, content, tag, media);
}

export async function createPostAsync(topic, title, content, tag = "", media = []) {
    const h = await getHandler();
    return h.createPostAsync(topic, title, content, tag, media);
}

export async function createComment(parentId, content) {
    const h = await getHandler();
    return h.createComment(parentId, content);
}

export async function createCommentAsync(parentId, content) {
    const h = await getHandler();
    return h.createCommentAsync(parentId, content);
}

export async function createVote(parentId, direction) {
    const h = await getHandler();
    return h.createVote(parentId, direction);
}

export async function cancelAll(reason = 'cancelled') {
    const h = await getHandler();
    return h.cancelAll(reason);
}

export async function resetSession(reason = 'session_reset') {
    const h = await getHandler();
    return h.resetSession(reason);
}

export async function deletePost(txhash) {
    const h = await getHandler();
    return h.deletePost(txhash);
}

export async function deleteUser() {
    const h = await getHandler();
    return h.deleteUser();
}

export async function blockUser(address, block = true) {
    const h = await getHandler();
    return h.blockUser(address, block);
}

export async function blockPost(txhash, block = true) {
    const h = await getHandler();
    return h.blockPost(txhash, block);
}

export async function unblockUser(address) {
    const h = await getHandler();
    return h.unblockUser(address);
}

export async function unblockPost(txhash) {
    const h = await getHandler();
    return h.unblockPost(txhash);
}

export async function blockCommunity(community) {
    const h = await getHandler();
    return h.blockCommunity(community);
}

export async function unblockCommunity(community) {
    const h = await getHandler();
    return h.unblockCommunity(community);
}

export async function reportPost(txhash, reason) {
    const h = await getHandler();
    return h.reportPost(txhash, reason);
}

export async function sendTokens(targetAddress, amountMirage) {
    const h = await getHandler();
    return h.sendTokens(targetAddress, amountMirage);
}

export async function giveAward(targetPostId, awardType) {
    const h = await getHandler();
    return h.giveAward(targetPostId, awardType);
}

const BALANCE_HOLD_KEY = 'user_balance_hold';
const BALANCE_HOLD_MS = 15000;

export function adjustBalanceOptimistic(deltaUmirage) {
    try {
        const current = Number(Storage.load('user_balance', '0') || 0);
        if (!Number.isFinite(current)) return;
        const next = Math.max(0, current + deltaUmirage);
        Storage.save('user_balance', String(next));
        window.dispatchEvent(new CustomEvent('balanceUpdated', { detail: next }));
        if (deltaUmirage < 0) {
            const existing = Storage.load(BALANCE_HOLD_KEY, null);
            const prevMin = Number(existing?.min_balance);
            const minBalance = Number.isFinite(prevMin) ? Math.min(prevMin, next) : next;
            const expiresAt = Date.now() + BALANCE_HOLD_MS;
            Storage.save(BALANCE_HOLD_KEY, {
                min_balance: minBalance,
                expires_at_ms: expiresAt,
            });
            console.debug('[tx.adjustBalanceOptimistic] hold', { minBalance, expiresAt });
        } else if (deltaUmirage > 0) {
            Storage.remove(BALANCE_HOLD_KEY);
        }
    } catch (_) { /* noop */ }
}

export async function refreshBalance() {
    const Storage = (await import('./Storage')).default;
    const Api = (await import('./api')).default;
    const publicKey = Storage.load('publicKey', '');
    if (!publicKey) return;
    try {
        const data = await Api.get('get_user_status', { address: publicKey, _cb: Date.now() });
        if (data) {
            const hold = Storage.load(BALANCE_HOLD_KEY, null);
            if (hold && typeof hold === 'object') {
                const now = Date.now();
                const expiresAt = Number(hold.expires_at_ms);
                const minBalance = Number(hold.min_balance);
                const raw = data.balance !== undefined ? data.balance : data.user_balance;
                const serverBalance = Number(raw);
                if (Number.isFinite(expiresAt) && now < expiresAt
                    && Number.isFinite(minBalance) && Number.isFinite(serverBalance)
                    && serverBalance > minBalance) {
                    const retryIn = Math.min(4000, Math.max(1000, expiresAt - now));
                    console.debug('[tx.refreshBalance] hold active, skip update', { serverBalance, minBalance, expiresAt, retryIn });
                    setTimeout(() => { void refreshBalance(); }, retryIn);
                    return;
                }
                Storage.remove(BALANCE_HOLD_KEY);
            }
            const h = await getHandler();
            h.cacheUserStatus(data);
        }
    } catch (e) {
        console.warn('[tx.refreshBalance] Failed:', e?.message || e);
    }
}

export async function subscribe(level, monthlyFeeUmirage, target) {
    const h = await getHandler();
    return h.subscribe(level, monthlyFeeUmirage, target);
}

export async function setAutoRenewal(autoRenew) {
    const h = await getHandler();
    return h.setAutoRenewal(autoRenew);
}

export async function followUser(address) {
    const h = await getHandler();
    return h.followUser(address);
}

export async function unfollowUser(address) {
    const h = await getHandler();
    return h.unfollowUser(address);
}

export async function joinCommunity(community) {
    const h = await getHandler();
    return h.joinCommunity(community);
}

export async function leaveCommunity(community) {
    const h = await getHandler();
    return h.leaveCommunity(community);
}

export async function editPost(overrideId, changes) {
    const h = await getHandler();
    return h.editPost(overrideId, changes);
}

// Optional helper used by ViewPostView; keep as no-op unless handler provides it
export async function reconcileAfterCommentsFetch(postId, root, children) {
    const h = await getHandler();
    if (typeof h.reconcileAfterCommentsFetch === 'function') {
        return h.reconcileAfterCommentsFetch(postId, root, children);
    }
    return undefined;
}

// Unified tx status polling: 4s initial delay, then 2s intervals, max 5 attempts
// Returns: { success, indexed, tx_type, details, error_details } or null if not found/timeout
export async function pollTxStatus(txHash, options = {}) {
    const {
        onProgress,
        initialDelay = 4000,
        interval = 2000,
        maxAttempts = 5,
        timeoutMs = 5000,
        requireIndexed = true,
        intervals,
    } = options;

    const hasCustomSchedule = Array.isArray(intervals) && intervals.length > 0;
    const attemptLimit = hasCustomSchedule ? intervals.length + 1 : maxAttempts;
    const delayBeforeFirst = hasCustomSchedule
        ? (options.initialDelay ?? 0)
        : initialDelay;

    if (hasCustomSchedule) {
        console.debug('[pollTxStatus] Using custom interval schedule:', intervals);
    }

    const Api = (await import('./api')).default;
    const Storage = (await import('./Storage')).default;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    // Get user address for inbox timestamp piggyback
    const address = Storage.load('publicKey', '');

    // Initial delay before first poll
    if (delayBeforeFirst > 0) {
        await sleep(delayBeforeFirst);
    }

    for (let attempt = 0; attempt < attemptLimit; attempt++) {
        try {
            if (onProgress) onProgress({ attempt: attempt + 1, maxAttempts: attemptLimit });

            const params = { hash: txHash };
            if (address) params.address = address;

            const res = await Api.get('get_tx_status', params, { timeoutMs });

            if (res && res.found) {
                if (!res.success) {
                    return {
                        success: false,
                        indexed: res.indexed,
                        tx_type: res.tx_type,
                        error_details: res.error_details,
                    };
                }
                if (res.indexed || !requireIndexed) {
                    return {
                        success: true,
                        indexed: !!res.indexed,
                        tx_type: res.tx_type,
                        details: res.details,
                    };
                }
            }
        } catch (err) {
            console.warn('[pollTxStatus] Attempt', attempt + 1, 'failed:', err?.message || err);
        }

        if (attempt < attemptLimit - 1) {
            const nextDelay = hasCustomSchedule ? intervals[attempt] : interval;
            if (nextDelay > 0) {
                await sleep(nextDelay);
            }
        }
    }

    return null;
}
