/**
 * Solana Bridge Utilities
 * 
 * Builds and sends burn transactions for bridging MIRAGE from Solana to Mirage.
 * 
 * NOTE: This module uses dynamic imports to lazy-load @solana/web3.js and @solana/spl-token
 * so they're only downloaded when the user actually needs Solana bridging.
 */

/* global BigInt */

// Lazy-loaded modules (populated on first use)
let solanaWeb3 = null;
let solanaSplToken = null;

// Anchor instruction discriminator for "burn"
// sha256("global:burn")[0..8] = [116, 110, 29, 56, 107, 219, 42, 93]
const BURN_DISCRIMINATOR = [116, 110, 29, 56, 107, 219, 42, 93];

/**
 * Lazy-load Solana dependencies
 */
async function loadSolanaDeps() {
    if (!solanaWeb3 || !solanaSplToken) {
        const [web3Module, splTokenModule] = await Promise.all([
            import('@solana/web3.js'),
            import('@solana/spl-token'),
        ]);
        solanaWeb3 = web3Module;
        solanaSplToken = splTokenModule;
    }
    return { solanaWeb3, solanaSplToken };
}

// PDA seeds
const BRIDGE_CONFIG_SEED = 'bridge_config';
const MINT_SEED = 'mint';
const BURN_RECORD_SEED = 'burn_record';

/**
 * Derive the bridge_config PDA
 */
function getBridgeConfigPDA(programId, PublicKey) {
    return PublicKey.findProgramAddressSync(
        [Buffer.from(BRIDGE_CONFIG_SEED)],
        programId
    );
}

/**
 * Derive the token mint PDA
 */
function getMintPDA(programId, PublicKey) {
    return PublicKey.findProgramAddressSync(
        [Buffer.from(MINT_SEED)],
        programId
    );
}

/**
 * Derive the burn_record PDA for a given nonce
 */
function getBurnRecordPDA(programId, burnNonce, PublicKey) {
    const nonceBuffer = Buffer.alloc(8);
    nonceBuffer.writeBigUInt64LE(BigInt(burnNonce));
    return PublicKey.findProgramAddressSync(
        [Buffer.from(BURN_RECORD_SEED), nonceBuffer],
        programId
    );
}

/**
 * Encode BurnParams for the instruction data
 * Layout: discriminator (8) + mirage_recipient (4 + len) + amount (8)
 */
function encodeBurnParams(mirageRecipient, amount) {
    const recipientBytes = Buffer.from(mirageRecipient, 'utf-8');
    const recipientLen = recipientBytes.length;
    
    // Total size: 8 (discriminator) + 4 (string len) + recipientLen + 8 (amount)
    const data = Buffer.alloc(8 + 4 + recipientLen + 8);
    let offset = 0;
    
    // Discriminator
    Buffer.from(BURN_DISCRIMINATOR).copy(data, offset);
    offset += 8;
    
    // String length (u32 little-endian)
    data.writeUInt32LE(recipientLen, offset);
    offset += 4;
    
    // String bytes
    recipientBytes.copy(data, offset);
    offset += recipientLen;
    
    // Amount (u64 little-endian)
    data.writeBigUInt64LE(BigInt(amount), offset);
    
    return data;
}

/**
 * Fetch the current burn nonce from the bridge config
 */
async function fetchBurnNonce(connection, programId, PublicKey) {
    const [bridgeConfigPDA] = getBridgeConfigPDA(programId, PublicKey);
    const accountInfo = await connection.getAccountInfo(bridgeConfigPDA);
    
    if (!accountInfo) {
        throw new Error('Bridge config account not found');
    }
    
    // BridgeConfig layout (after 8-byte discriminator):
    // authority: 32 bytes
    // mint: 32 bytes
    // mirage_chain_id: 4 + len bytes (string)
    // attestation_threshold: 8 bytes
    // total_minted: 8 bytes
    // total_burned: 8 bytes
    // burn_nonce: 8 bytes
    // paused: 1 byte
    // bump: 1 byte
    
    const data = accountInfo.data;
    
    // Skip discriminator (8) + authority (32) + mint (32) = 72
    let offset = 72;
    
    // Read string length for mirage_chain_id
    const chainIdLen = data.readUInt32LE(offset);
    offset += 4 + chainIdLen;
    
    // Skip attestation_threshold (8) + total_minted (8) + total_burned (8) = 24
    offset += 24;
    
    // Read burn_nonce
    const burnNonce = data.readBigUInt64LE(offset);
    
    return burnNonce;
}

/**
 * Check if the bridge is paused
 */
async function isBridgePaused(connection, programId, PublicKey) {
    const [bridgeConfigPDA] = getBridgeConfigPDA(programId, PublicKey);
    const accountInfo = await connection.getAccountInfo(bridgeConfigPDA);
    
    if (!accountInfo) {
        throw new Error('Bridge config account not found');
    }
    
    const data = accountInfo.data;
    
    // Navigate to paused field (after burn_nonce)
    let offset = 72; // discriminator + authority + mint
    const chainIdLen = data.readUInt32LE(offset);
    offset += 4 + chainIdLen;
    offset += 24; // attestation_threshold + total_minted + total_burned
    offset += 8; // burn_nonce
    
    const paused = data.readUInt8(offset) !== 0;
    return paused;
}

/**
 * Build a burn transaction for the Solana bridge
 * 
 * @param {Object} params
 * @param {Connection} params.connection - Solana connection
 * @param {PublicKey} params.programId - Bridge program ID
 * @param {PublicKey} params.userPublicKey - User's Solana wallet public key
 * @param {string} params.mirageRecipient - Recipient address on Mirage (mirage1...)
 * @param {number|bigint} params.amount - Amount in base units (umirage, 6 decimals)
 * @returns {Promise<Transaction>} - Unsigned transaction ready for signing
 */
async function buildBurnTransaction({
    connection,
    programId,
    userPublicKey,
    mirageRecipient,
    amount,
}) {
    const { solanaWeb3, solanaSplToken } = await loadSolanaDeps();
    const { PublicKey, Transaction, TransactionInstruction, SystemProgram } = solanaWeb3;
    const { getAssociatedTokenAddressSync, TOKEN_PROGRAM_ID } = solanaSplToken;
    
    // Validate mirage address format
    if (!mirageRecipient.startsWith('mirage1')) {
        throw new Error('Invalid Mirage recipient address');
    }
    
    // Check if bridge is paused
    const paused = await isBridgePaused(connection, programId, PublicKey);
    if (paused) {
        throw new Error('Bridge is currently paused');
    }
    
    // Get PDAs
    const [bridgeConfigPDA] = getBridgeConfigPDA(programId, PublicKey);
    const [tokenMintPDA] = getMintPDA(programId, PublicKey);
    
    // Fetch current burn nonce to derive burn_record PDA
    const burnNonce = await fetchBurnNonce(connection, programId, PublicKey);
    const [burnRecordPDA] = getBurnRecordPDA(programId, burnNonce, PublicKey);
    
    // Get user's associated token account
    const userTokenAccount = getAssociatedTokenAddressSync(
        tokenMintPDA,
        userPublicKey,
        true // allowOwnerOffCurve
    );
    
    // Check token balance
    try {
        const tokenBalance = await connection.getTokenAccountBalance(userTokenAccount);
        const balance = BigInt(tokenBalance.value.amount);
        if (balance < BigInt(amount)) {
            throw new Error(`Insufficient balance. Have ${balance}, need ${amount}`);
        }
    } catch (e) {
        if (e.message.includes('Insufficient balance')) {
            throw e;
        }
        throw new Error('Token account not found. Do you have MIRAGE tokens?');
    }
    
    // Build instruction data
    const instructionData = encodeBurnParams(mirageRecipient, amount);
    
    // Build the burn instruction
    const burnInstruction = new TransactionInstruction({
        keys: [
            { pubkey: userPublicKey, isSigner: true, isWritable: true },
            { pubkey: userTokenAccount, isSigner: false, isWritable: true },
            { pubkey: tokenMintPDA, isSigner: false, isWritable: true },
            { pubkey: bridgeConfigPDA, isSigner: false, isWritable: true },
            { pubkey: burnRecordPDA, isSigner: false, isWritable: true },
            { pubkey: TOKEN_PROGRAM_ID, isSigner: false, isWritable: false },
            { pubkey: SystemProgram.programId, isSigner: false, isWritable: false },
        ],
        programId,
        data: instructionData,
    });
    
    // Build transaction
    const transaction = new Transaction();
    transaction.add(burnInstruction);
    
    // Get recent blockhash
    const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash('confirmed');
    transaction.recentBlockhash = blockhash;
    transaction.lastValidBlockHeight = lastValidBlockHeight;
    transaction.feePayer = userPublicKey;
    
    return transaction;
}

/**
 * Execute a burn transaction via Phantom wallet
 * 
 * @param {Object} params
 * @param {string} params.rpcUrl - Solana RPC URL
 * @param {string} params.programIdStr - Bridge program ID as base58 string
 * @param {string} params.mirageRecipient - Recipient address on Mirage
 * @param {number} params.amount - Amount in base units
 * @param {function} params.onStatus - Status callback
 * @returns {Promise<{signature: string, burnNonce: bigint}>}
 */
export async function executeBurn({
    rpcUrl,
    programIdStr,
    mirageRecipient,
    amount,
    onStatus = () => {},
}) {
    // Check for Phantom
    const { solana } = window;
    if (!solana?.isPhantom) {
        throw new Error('Phantom wallet not found');
    }
    
    if (!solana.publicKey) {
        throw new Error('Wallet not connected');
    }
    
    onStatus('Loading Solana libraries...');
    
    // Lazy load Solana dependencies
    const { solanaWeb3 } = await loadSolanaDeps();
    const { Connection, PublicKey } = solanaWeb3;
    
    onStatus('Building transaction...');
    
    const connection = new Connection(rpcUrl, 'confirmed');
    const programId = new PublicKey(programIdStr);
    const userPublicKey = solana.publicKey;
    
    // Get burn nonce before transaction (for tracking)
    const burnNonce = await fetchBurnNonce(connection, programId, PublicKey);
    
    // Build the transaction
    const transaction = await buildBurnTransaction({
        connection,
        programId,
        userPublicKey,
        mirageRecipient,
        amount,
    });
    
    onStatus('Waiting for wallet approval...');
    
    // Sign and send via Phantom
    const { signature } = await solana.signAndSendTransaction(transaction);
    
    onStatus('Confirming transaction...');
    
    // Wait for confirmation
    const confirmation = await connection.confirmTransaction({
        signature,
        blockhash: transaction.recentBlockhash,
        lastValidBlockHeight: transaction.lastValidBlockHeight,
    }, 'confirmed');
    
    if (confirmation.value.err) {
        throw new Error(`Transaction failed: ${JSON.stringify(confirmation.value.err)}`);
    }
    
    return {
        signature,
        burnNonce,
    };
}

/**
 * Fetch MIRAGE token balance for a Solana wallet
 * This is a lightweight function that uses RPC directly without heavy deps
 * 
 * @param {string} rpcUrl - Solana RPC URL
 * @param {string} walletAddress - User's Solana wallet address
 * @param {string} tokenMintAddress - MIRAGE token mint address
 * @returns {Promise<number>} - Balance in MIRAGE (not base units)
 */
export async function fetchTokenBalance(rpcUrl, walletAddress, tokenMintAddress) {
    // Use fetch directly to avoid loading the full Solana SDK just for balance
    const response = await fetch(rpcUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            jsonrpc: '2.0',
            id: 1,
            method: 'getTokenAccountsByOwner',
            params: [
                walletAddress,
                { mint: tokenMintAddress },
                { encoding: 'jsonParsed' }
            ]
        })
    });
    
    const data = await response.json();
    
    if (data.result?.value?.length > 0) {
        let totalBalance = 0;
        for (const account of data.result.value) {
            const tokenData = account.account?.data?.parsed?.info;
            if (tokenData) {
                totalBalance += tokenData.tokenAmount?.uiAmount || 0;
            }
        }
        return totalBalance;
    }
    
    return 0;
}
