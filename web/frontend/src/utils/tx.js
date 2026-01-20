// Lightweight facade that lazily loads the heavy TransactionHandler only on demand
let handlerPromise = null;

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

export async function cacheConfigData(data) {
    const h = await getHandler();
    return h.cacheConfigData(data);
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

export async function createPost(topic, title, content, tag = "") {
    const h = await getHandler();
    return h.createPost(topic, title, content, tag);
}

export async function createPostAsync(topic, title, content, tag = "") {
    const h = await getHandler();
    return h.createPostAsync(topic, title, content, tag);
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

export async function performTransaction(tx, challenge, privateKeyHex, signerAddress, forcePow = false) {
    const h = await getHandler();
    return h.performTransaction(tx, challenge, privateKeyHex, signerAddress, forcePow);
}

export async function deletePost(txhash) {
    const h = await getHandler();
    return h.deletePost(txhash);
}

export async function blockUser(address, block = true) {
    const h = await getHandler();
    return h.blockUser(address, block);
}

export async function blockPost(txhash, block = true) {
    const h = await getHandler();
    return h.blockPost(txhash, block);
}

export async function reportPost(txhash, reason) {
    const h = await getHandler();
    return h.reportPost(txhash, reason);
}

export async function sendTokens(targetAddress, amountMirage) {
    const h = await getHandler();
    return h.sendTokens(targetAddress, amountMirage);
}

export async function upgradeLevel(level, monthlyFeeUmirage) {
    const h = await getHandler();
    return h.upgradeLevel(level, monthlyFeeUmirage);
}

export async function setAutoRenewal(autoRenew) {
    const h = await getHandler();
    return h.setAutoRenewal(autoRenew);
}

export async function ibcTransfer(receiver, amountUmirage, sourceChannel, timeoutSeconds = 600) {
    const h = await getHandler();
    return h.ibcTransfer(receiver, amountUmirage, sourceChannel, timeoutSeconds);
}

export async function bridgeBurn(destinationChain, destinationAddress, amountUmirage) {
    const h = await getHandler();
    return h.bridgeBurn(destinationChain, destinationAddress, amountUmirage);
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
    } = options;

    const Api = (await import('../lib/api')).default;
    const Storage = (await import('./Storage')).default;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    // Get user address for inbox timestamp piggyback
    const address = Storage.load('publicKey', '');

    // Initial delay before first poll
    await sleep(initialDelay);

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        try {
            if (onProgress) onProgress({ attempt: attempt + 1, maxAttempts });

            const params = { hash: txHash };
            if (address) params.address = address;

            const res = await Api.get('get_tx_status', params, { timeoutMs });

            // Dispatch inbox timestamp if present
            if (res && typeof res.latest_inbox_timestamp === 'number') {
                window.dispatchEvent(new CustomEvent('inboxTimestamp', { detail: res.latest_inbox_timestamp }));
            }

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

        if (attempt < maxAttempts - 1) {
            await sleep(interval);
        }
    }

    return null;
}

