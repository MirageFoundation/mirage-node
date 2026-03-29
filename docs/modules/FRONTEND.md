# Mirage Web Frontend

This document provides a comprehensive technical overview of the Mirage web frontend, a React-based single-page application that implements the user interface for the Mirage social platform. It is intended for senior engineers, architects, and project managers who need to understand the system's design philosophy, transaction handling architecture, and the rationale behind key implementation choices.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Component Structure](#component-structure)
4. [State Management](#state-management)
5. [Transaction Handler](#transaction-handler)
6. [Client-Side Cryptography](#client-side-cryptography)
7. [Proof-of-Work Computation](#proof-of-work-computation)
8. [API Integration](#api-integration)
9. [View Components](#view-components)
10. [Caching and Storage](#caching-and-storage)
11. [User Experience Design](#user-experience-design)
12. [Security Considerations](#security-considerations)
13. [Build and Deployment](#build-and-deployment)

---

## Overview

The frontend is a React SPA that provides:

- Account creation and management (seed phrase-based)
- Content creation (posts, comments, votes)
- Social features (follow users/topics, block content)
- Subscription management and token transfers
- Cross-chain bridging UI (Solana)
- Personalized feeds and discovery

**Key Design Principle:** The frontend handles all cryptographic operations locally. Private keys never leave the browser. The backend only receives signed messages and public keys.

---

## Architecture Philosophy

### Client-Side Key Management

Unlike traditional blockchain apps that use browser extensions (MetaMask, Phantom), Mirage manages keys entirely in-browser:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KEY MANAGEMENT MODEL                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  Traditional Model:                                                          │
│    [Browser] ──request──► [Extension] ──sign──► [DApp]                      │
│                                                                              │
│  Mirage Model:                                                               │
│    [Browser/LocalStorage]                                                    │
│       └── seedPhrase (BIP39 mnemonic)                                       │
│       └── publicKey (derived address)                                       │
│           └── Derive private key on-demand                                  │
│           └── Sign in-browser                                               │
│           └── Submit to backend API                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Benefits:**
- No extension dependency
- Works on all browsers/devices
- Simpler onboarding
- Full control over UX

**Trade-offs:**
- User must backup seed phrase
- Browser storage security depends on device security

### Lazy Loading and Code Splitting

The app uses React's lazy loading to minimize initial bundle size:

```javascript
const MainView = lazyWithRetry(() => import('./views/MainView'));
const CreatePostView = lazyWithRetry(() => import('./views/CreatePostView'));
// ... other views
```

The `lazyWithRetry` wrapper handles chunk load errors gracefully, triggering a page reload when deployed updates cause stale chunk references.

### Transaction Queue Model

All blockchain interactions flow through a single `TransactionHandler` singleton that:
- Queues transactions sequentially
- Computes PoW in a Web Worker (for free users)
- Signs messages client-side
- Submits to backend API
- Tracks pending state for UI feedback

---

## Component Structure

### Directory Layout

```
web/frontend/src/
├── App.js                 # Root component, routing, theme
├── index.js               # Entry point
├── views/
│   ├── MainView.js        # Feed views (home, following, topic)
│   ├── CreatePostView.js  # Post/comment creation
│   ├── ViewPostView.js    # Thread view with comments
│   ├── ProfileView.js     # User profile
│   ├── SettingsView.js    # User settings
│   ├── SubscriptionView.js # Subscription management
│   ├── BridgeView.js      # Cross-chain bridging
│   └── ...
├── components/
│   ├── CardView.js        # Post card display
│   ├── VoteSection.js     # Upvote/downvote controls
│   ├── TopBar.js          # Navigation header
│   ├── Sidebar.js         # Navigation sidebar
│   ├── MarkdownEditor.js  # Content editor
│   └── ...
├── utils/
│   ├── api.js                 # HTTP client wrapper
│   ├── chainParams.js         # Username limits from cached chain config
│   ├── TransactionHandler.js  # Transaction queue and signing
│   ├── CryptoUtils.js         # Key derivation
│   ├── Storage.js             # LocalStorage wrapper
│   ├── tx.js                  # Transaction facade
│   └── ...
├── config/
│   └── chainParams.js     # Chain parameter caching
└── styled/
    └── ...                # Styled-components themes
```

### Core Components

| Component | Purpose |
|-----------|---------|
| `App.js` | Root routing, theme provider, global state |
| `MainView.js` | Feed rendering (home, following, topic-specific) |
| `CardView.js` | Individual post display with metadata |
| `VoteSection.js` | Vote buttons with optimistic updates |
| `TransactionHandler.js` | Transaction queue, PoW, signing |

---

## State Management

### Local State Pattern

The frontend uses React's built-in state management rather than Redux:

```javascript
// View-level state for posts
const [posts, setPosts] = useState([]);
const [loading, setLoading] = useState(true);

// TransactionHandler callbacks for cross-component updates
useEffect(() => {
    tx.updatePostCallback((postId, updates) => {
        setPosts(prev => prev.map(p =>
            p.txhash.toLowerCase() === postId.toLowerCase()
                ? { ...p, ...updates }
                : p
        ));
    });
}, []);
```

### Storage Layer

LocalStorage is used for persistent state:

```javascript
// Storage utility provides typed access
Storage.save('seedPhrase', mnemonic);
Storage.save('publicKey', address);
Storage.save('user_level', String(level));
Storage.save('user_balance', String(balance));
```

**Stored Items:**
- `seedPhrase` - User's BIP39 mnemonic (critical)
- `publicKey` - Derived Mirage address
- `user_level` - Subscription tier (0-4)
- `user_balance` - Token balance (umirage)
- `theme` - Light/dark preference
- `lastRoute` - Restore navigation state

---

## Transaction Handler

### Singleton Pattern

The `TransactionHandler` is a singleton that manages all blockchain interactions:

```javascript
class TransactionHandler {
    constructor() {
        if (!TransactionHandler.instance) {
            this.transactions = [];      // Pending queue
            this.isProcessing = false;   // Lock for sequential processing
            this.pendingVotes = new Map();    // Vote tracking
            this.pendingFollows = new Map();  // Follow tracking
            TransactionHandler.instance = this;
        }
        return TransactionHandler.instance;
    }
}
```

### Transaction Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TRANSACTION LIFECYCLE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  1. User Action (e.g., click upvote)                                        │
│     ↓                                                                        │
│  2. Queue Transaction                                                        │
│     - Add to this.transactions array                                         │
│     - Track in pendingVotes/pendingFollows                                   │
│     - Notify listeners for optimistic UI                                     │
│     ↓                                                                        │
│  3. Process Queue (sequential)                                               │
│     - Fetch chain parameters (difficulty, block hash)                        │
│     - Determine if PoW needed (free user) or skip (subscriber)               │
│     ↓                                                                        │
│  4. Build Canonical Bytes                                                    │
│     - Deterministic serialization matching chain ante handler                │
│     - Include: pubkey, block_hash, difficulty, timestamp, payload            │
│     ↓                                                                        │
│  5. Compute PoW (free users only)                                            │
│     - Spawn Web Worker                                                       │
│     - Argon2id hashing until leading zeros ≥ difficulty                      │
│     ↓                                                                        │
│  6. Sign Message                                                             │
│     - Derive private key from seed                                           │
│     - secp256k1 sign(SHA256(canonical_bytes + ":" + pow))                    │
│     ↓                                                                        │
│  7. Submit to Backend                                                        │
│     - POST /api/core/{action}                                                │
│     - Include: pubkey, signature, payload, pow (if applicable)               │
│     ↓                                                                        │
│  8. Handle Response                                                          │
│     - Update pending state                                                   │
│     - Notify listeners                                                       │
│     - Show success/error toast                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Pending State Tracking

The handler tracks in-flight operations for optimistic UI:

```javascript
// Vote tracking
this.pendingVotes = new Map();  // postId -> { direction, queuePosition }

// Check if vote is pending
isPendingVote(postId) {
    return this.pendingVotes.has(postId.toLowerCase());
}

// Get pending vote direction for UI
getPendingVoteDirection(postId) {
    const entry = this.pendingVotes.get(postId.toLowerCase());
    return entry ? entry.direction : null;
}
```

Components subscribe to updates:

```javascript
// VoteSection subscribes to pending votes
useEffect(() => {
    const unsubscribe = tx.addVoteListener((pending) => {
        setPendingVotes(pending);
    });
    return unsubscribe;
}, []);
```

### Status Updates

The handler provides queue status for UI feedback:

```javascript
getQueueStatus() {
    return {
        status: this._currentStatus,     // 'idle', 'preparing', 'submitting'
        position: this.processedTransactions,
        total: this.totalTransactions,
        elapsed: elapsedSeconds,
        isActive: this._currentStatus !== 'idle'
    };
}
```

---

## Client-Side Cryptography

### Key Derivation

Keys are derived from BIP39 mnemonics using Cosmos-compatible paths:

```javascript
// BIP44 path for Cosmos chains
const HD_PATH = "m/44'/118'/0'/0/0";

export const derivePrivateKeyFromSeed = (seedPhrase) => {
    const seed = mnemonicToSeedSync(seedPhrase, "");
    const hd = HDKey.fromMasterSeed(seed);
    const child = hd.derive(HD_PATH);
    return bytesToHex(child.privateKey);
};

export const derivePublicKeyFromSeed = (seedPhrase) => {
    const seed = mnemonicToSeedSync(seedPhrase, "");
    const hd = HDKey.fromMasterSeed(seed);
    const child = hd.derive(HD_PATH);
    const pubBytes = secp256k1GetPublicKey(child.privateKey, true);  // compressed
    return pubkeyHexToMirageAddress(bytesToHex(pubBytes));
};
```

### Address Derivation

Mirage addresses follow Cosmos SDK conventions:

```javascript
const pubkeyHexToMirageAddress = (pubkeyHex) => {
    // SHA256 -> RIPEMD160 -> Bech32
    const sha = CryptoJS.SHA256(CryptoJS.enc.Hex.parse(pubkeyHex));
    const rip = CryptoJS.RIPEMD160(sha);
    const addrBytes = hexToBytes(rip.toString(CryptoJS.enc.Hex));
    const words = bech32.toWords(addrBytes);
    return bech32.encode('mirage', words);  // mirage1...
};
```

### Message Signing

Messages are signed using secp256k1:

```javascript
async function signMessage(messageBytes, privateKeyHex) {
    await ensureCosmCrypto();
    const privBytes = hexToBytes(privateKeyHex);
    const messageHash = __CosmSha256(messageBytes);
    const signature = await __CosmSecp256k1.createSignature(
        messageHash,
        privBytes
    );
    return signature.toFixedLength();  // 64 bytes (r||s)
}
```

---

## Proof-of-Work Computation

### Web Worker Architecture

PoW computation runs in a dedicated Web Worker to avoid blocking the UI:

```javascript
// Spawn worker
const worker = new Worker("/pow/worker.js");

// Send work request
worker.postMessage({
    baseBytes: bytesToHex(canonicalBytes),
    salt: transaction.last_block_hash,
    difficulty: transaction.pow_difficulty,
});

// Receive result
worker.onmessage = (e) => {
    const { pow, leading_zeros } = e.data;
    // Continue with signing
};
```

### Canonical Message Format

The frontend builds identical canonical bytes to the chain's ante handler:

```javascript
// Example: MsgVote canonical bytes
const prefix = new TextEncoder().encode("mirage.core.v1:MsgVote\x00");
baseBytes = concat(
    prefix,
    tag2, encBytes(pubBytes),           // envelope_pubkey
    tag3, encBytes(hexToBytes(blockHash)), // envelope_block_hash
    tag4, uvarint(difficulty),          // envelope_difficulty
    tag6, uvarint64(timestamp),         // envelope_timestamp
    tag100, encStr(target),             // target post
    tag101, uvarint(direction),         // vote direction
);
```

**Critical:** This serialization must exactly match the chain's `BuildCanonicalBytes` function. Any mismatch causes signature verification failure.

### Difficulty Handling

Free users compute PoW; subscribers skip it:

```javascript
const userLevel = Number(Storage.load('user_level', '0')) || 0;
const canSkipPow = userLevel >= 1 || powDifficulty <= 0;

if (canSkipPow) {
    // Subscriber path: zero out PoW fields
    transaction.pow_difficulty = 0;
    transaction.pow = 0;
    // Submit directly
} else {
    // Free user path: compute PoW in worker
    const worker = new Worker("/pow/worker.js");
    // ... PoW computation
}
```

---

## API Integration

### API Client

The `Api` module provides a minimal fetch wrapper:

```javascript
const API_BASE = '/api';  // Relative path, proxied by Caddy

async function get(path, params, options) {
    const url = buildUrl(path, params);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options?.timeoutMs || 10000);
    
    const resp = await fetch(url, { signal: controller.signal });
    return await resp.json();
}

async function post(path, body, options) {
    const url = buildUrl(path);
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    return await resp.json();
}
```

### Key Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/get_parameters` | GET | Block hash, difficulty, balance |
| `/api/get_chain_config` | GET | Chain params, tier configs |
| `/api/get_node_config` | GET | Node static config, feature flags |
| `/api/get_user_status` | GET | User status (level, balance, subscription) |
| `/api/get_posts` | GET | Feed data |
| `/api/get_comments` | GET | Thread comments |
| `/api/get_profile` | GET | User profile data |
| `/api/get_tx_status` | GET | Transaction confirmation |
| `/api/core/post` | POST | Create post/comment |
| `/api/core/vote` | POST | Submit vote |
| `/api/core/set_username` | POST | Set username |
| `/api/bridge/burn` | POST | Bridge burn transaction |
| `/api/bridge/config` | GET | Bridge configuration (chains, fees) |
| `/api/bridge/status` | GET | Query bridge status and attestation progress |

---

## View Components

### MainView (Feed)

The main feed view supports multiple modes:

```javascript
// Route patterns
/home           → Home feed (personalized)
/following      → Following feed (users + topics)
/t/{topic}      → Topic-specific feed
/discover       → Discovery/trending
```

**Feed Loading:**
```javascript
const loadPosts = async () => {
    const params = {
        address: publicKey,
        limit: 20,
        offset: 0,
        topic: currentTopic || undefined,
        filter: feedType,
    };
    const data = await Api.get('get_posts', params);
    setPosts(data.posts || []);
};
```

### ViewPostView (Thread)

Displays a post with its comment tree:

```javascript
const loadComments = async () => {
    const data = await Api.get('get_comments', { id: postId, address });
    setRootPost(data.root);
    setComments(data.children || []);
};
```

Comments are rendered recursively with indentation based on depth.

### CardView (Post Card)

Each post is rendered as a card with:
- Author info (username, address, tier badge)
- Content (markdown rendered)
- Voting controls
- Metadata (timestamp, topic, comment count)

```javascript
<CardView
    post={post}
    onVote={handleVote}
    onComment={handleComment}
    showTopic={!isSingleTopic}
/>
```

---

## Caching and Storage

### Chain Parameter Cache

Chain parameters are cached to reduce API calls:

```javascript
// chainParams.js
let cachedParams = null;
let cacheTime = 0;
const CACHE_TTL = 60000;  // 1 minute

export async function getChainParams() {
    if (cachedParams && Date.now() - cacheTime < CACHE_TTL) {
        return cachedParams;
    }
    const data = await Api.get('get_chain_config');
    cachedParams = data;
    cacheTime = Date.now();
    return data;
}
```

### Username Cache

Username lookups are cached to avoid repeated API calls:

```javascript
// UsernameCache.js
const cache = new Map();
const CACHE_TTL = 300000;  // 5 minutes

export async function getUsername(address) {
    const cached = cache.get(address);
    if (cached && Date.now() - cached.time < CACHE_TTL) {
        return cached.username;
    }
    const data = await Api.get('get_address_from_username', { address });
    cache.set(address, { username: data.username, time: Date.now() });
    return data.username;
}
```

### Profile Cache

Profile data is cached with a shorter TTL:

```javascript
// ProfileCache.js
export async function getProfile(address) {
    // Check cache
    // Fetch if stale
    // Update cache
    // Return profile
}
```

---

## User Experience Design

### Optimistic Updates

Votes appear instantly before blockchain confirmation:

```javascript
// When vote button clicked
const handleVote = async (direction) => {
    // 1. Update UI immediately
    setLocalDirection(direction);
    setLocalPoints(currentPoints + direction);
    
    // 2. Submit to chain
    const result = await tx.createVote(postId, direction);
    
    // 3. Reconcile with server response
    if (!result.success) {
        // Revert optimistic update
        setLocalDirection(previousDirection);
        setLocalPoints(previousPoints);
    }
};
```

### Loading States

The app shows appropriate loading states:

```javascript
{loading ? (
    <Spinner />
) : posts.length === 0 ? (
    <EmptyState message="No posts yet" />
) : (
    posts.map(post => <CardView key={post.txhash} post={post} />)
)}
```

### Error Handling

Errors are displayed via toast notifications:

```javascript
import { updateNotification } from './utils/notifications';

// Success
updateNotification("Post created successfully");

// Error
updateNotification("Failed to create post: " + error.message, 10, true);
```

### Transaction Status Polling

After submission, the frontend polls for confirmation:

```javascript
export async function pollTxStatus(txHash, options = {}) {
    const { initialDelay = 4000, interval = 2000, maxAttempts = 5 } = options;
    
    await sleep(initialDelay);
    
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const res = await Api.get('get_tx_status', { hash: txHash });
        
        if (res?.found && res?.indexed) {
            return {
                success: res.success,
                indexed: true,
                tx_type: res.tx_type,
                details: res.details,
            };
        }
        
        await sleep(interval);
    }
    
    return null;  // Timeout
}
```

---

## Security Considerations

### Seed Phrase Storage

The seed phrase is stored in LocalStorage. This is a deliberate trade-off:

**Risks:**
- XSS attacks could steal the seed
- Physical device access exposes the seed
- Browser extensions could access LocalStorage

**Mitigations:**
- CSP headers prevent XSS
- Users are advised to use dedicated browsers
- Mobile app (future) will use secure storage

### Key Derivation On-Demand

Private keys are derived on-demand, not stored:

```javascript
// Private key is derived when needed, then discarded
const privateKeyHex = derivePrivateKeyFromSeed(seedPhrase);
const result = await signAndSubmit(tx, privateKeyHex);
// privateKeyHex goes out of scope
```

### Input Validation

User inputs are validated before submission:

```javascript
// Username validation
if (!username.match(/^[A-Za-z0-9-]+$/)) {
    return { success: false, error: "Invalid username format" };
}
if (username.length < minUsername || username.length > maxUsername) {
    return { success: false, error: "Invalid username length" };
}
```

### CORS and API Security

The frontend only communicates with its own backend:
- API calls go to `/api/*` (same origin via Caddy proxy)
- No cross-origin requests to other domains
- Backend validates all signatures server-side

---

## Build and Deployment

### Build Process

```bash
# Development
npm start

# Production build
npm run build
```

### Environment Variables

```bash
REACT_APP_VERSION       # App version string
REACT_APP_BUILD_ID      # Build identifier
```

### Deployment

The built `build/` directory is served by Caddy:

```
/                → build/index.html
/static/*        → build/static/*
/pow/worker.js   → PoW Web Worker
/api/*           → Proxy to backend (port 5000)
```

### Chunk Load Error Handling

When new versions are deployed, users with cached main.js may fail to load chunks:

```javascript
function lazyWithRetry(importFn) {
    return React.lazy(() =>
        importFn().catch((error) => {
            const isChunkError = 
                error?.name === 'ChunkLoadError' ||
                error?.message?.includes('Loading chunk');
            
            if (isChunkError && !sessionStorage.getItem('chunk_reload_attempted')) {
                sessionStorage.setItem('chunk_reload_attempted', 'true');
                window.location.reload();
                return new Promise(() => {});  // Never resolve
            }
            throw error;
        })
    );
}
```

This ensures users always get the latest version after a deployment.

---

## Performance Considerations

### Bundle Size

- Lazy loading splits views into separate chunks
- TransactionHandler loads on-demand via `tx.js` facade
- Heavy crypto libraries load only when needed

### Rendering Optimization

- Feed uses pagination (not infinite scroll)
- Posts are keyed by `txhash` for stable identity
- Memoization for expensive computations

### Network Efficiency

- Chain params cached for 1 minute
- Username lookups cached for 5 minutes
- Batch requests where possible

### PoW Performance

- Runs in Web Worker (non-blocking)
- Typical solve time: 1-5 seconds at difficulty 10-12
- Progress updates to UI during computation
