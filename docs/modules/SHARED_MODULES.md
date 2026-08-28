# Mirage Shared Modules

This document provides a comprehensive technical overview of the shared Python modules used across multiple Mirage components. These modules ensure consistency between the web backend, indexer, and other Python services. This documentation is intended for senior engineers and architects who need to understand the cross-cutting concerns and why certain design decisions were made.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Datatypes Module](#datatypes-module)
4. [Canonical Serialization Module](#canonical-serialization-module)
5. [Configuration Module](#configuration-module)
6. [Logging Setup Module](#logging-setup-module)
7. [Client Module](#client-module)
8. [Cross-Language Consistency](#cross-language-consistency)
9. [Testing Considerations](#testing-considerations)

---

## Overview

The `shared/` directory contains Python modules that are imported by multiple services:

| Module | Purpose |
|--------|---------|
| `datatypes.py` | Dynamic protobuf message classes for custom Mirage types |
| `canon.py` | Canonical byte serialization for relay signature verification |
| `config.py` | Centralized configuration loading from node HOME files + DB URL helpers |
| `logging_setup.py` | Structured logging with date-based rotation |
| `client.py` | gRPC client utilities (optional) |
| `fingerprint.py` | Device fingerprinting utilities (fraud detection) |
| `push.py` | Push notification sending (Expo) — writes to backend DB |
| `inbox.py` | Inbox/notification helpers — reads from both DBs |

**Key Design Principle:** These modules exist to prevent code duplication and ensure identical behavior across services. When multiple services need to perform the same operation (e.g., serialize a message for signature verification), they must produce byte-identical results.

---

## Architecture Philosophy

### Why Shared Modules?

The Mirage system has multiple Python processes that must agree on:

1. **Message Formats** - Protobuf definitions must match exactly
2. **Canonical Bytes** - Signature verification requires identical serialization
3. **Configuration** - All services read from the same node HOME directory
4. **Logging** - Consistent format enables centralized log analysis

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SHARED MODULE CONSUMERS                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │  Web Backend │    │   Indexer    │    │   Scripts    │                   │
│  │   (Flask)    │    │   (Python)   │    │  (various)   │                   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                   │
│         │                   │                   │                           │
│         └───────────────────┼───────────────────┘                           │
│                             │                                               │
│                    ┌────────┴────────┐                                      │
│                    │  shared/*.py    │                                      │
│                    │  - datatypes    │                                      │
│                    │  - canon        │                                      │
│                    │  - config       │                                      │
│                    │  - logging      │                                      │
│                    └─────────────────┘                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Single Source of Truth

The Go blockchain defines message formats in `.proto` files. The shared modules mirror these definitions in Python, ensuring:

- Python services can construct valid protobuf messages
- Signature verification produces identical bytes to Go
- Field numbers and types match exactly

---

## Datatypes Module

### Purpose

`datatypes.py` dynamically builds protobuf message classes without requiring code generation from `.proto` files. This approach:

- Avoids maintaining separate generated Python protobuf files
- Ensures message classes are always available at runtime
- Allows quick iteration without protoc compilation step

### Implementation

The module uses Google's protobuf descriptor APIs to build message definitions at import time:

```python
def _build_pool():
    pool = descriptor_pool.DescriptorPool()
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "mirage_messages.proto"
    file_proto.package = "mirage.core.v1"
    file_proto.syntax = "proto3"
    
    # Define MsgPost
    msg = file_proto.message_type.add()
    msg.name = "MsgPost"
    add_f(msg, "authority", 1, TYPE_STRING)
    add_f(msg, "envelope_pubkey", 2, TYPE_BYTES)
    add_f(msg, "envelope_block_hash", 3, TYPE_BYTES)
    add_f(msg, "envelope_difficulty", 4, TYPE_UINT64)
    add_f(msg, "envelope_pow", 5, TYPE_UINT64)
    add_f(msg, "envelope_timestamp", 6, TYPE_UINT64)
    add_f(msg, "envelope_signature", 10, TYPE_BYTES)
    add_f(msg, "target", 100, TYPE_STRING)
    add_f(msg, "community", 101, TYPE_STRING)
    add_f(msg, "title", 102, TYPE_STRING)
    add_f(msg, "content", 103, TYPE_STRING)
    add_f(msg, "tag", 104, TYPE_STRING)
    
    pool.Add(file_proto)
    return pool
```

### Field Number Convention

All Mirage messages follow a consistent field numbering:

| Range | Purpose |
|-------|---------|
| 1 | `authority` - Validator address (set by backend) |
| 2-9 | Envelope fields (pubkey, block_hash, difficulty, pow, timestamp) |
| 10 | `envelope_signature` - User's signature |
| 100+ | Payload fields (message-specific data) |

This convention ensures the envelope (authentication wrapper) is consistent across all message types.

### Exported Classes

The module exports all message types needed by Python services:

```python
# Core messages
MsgPost, MsgEdit, MsgVote, MsgDelete
MsgSetUsername, MsgSendTokens
MsgFollowUser, MsgUnfollowUser
MsgJoinCommunity, MsgLeaveCommunity
MsgCreateCurationTeam, MsgSetCurationPreference
MsgInviteCurator, MsgAcceptCuratorInvite
MsgBlockPost, MsgUnblockPost
MsgBlockUser, MsgUnblockUser
MsgBlockCommunity, MsgUnblockCommunity

# Subscription messages
MsgSubscribe, MsgSetAutoRenewal, MsgSetLevel

# Query types
QueryParamsRequest, QueryParamsResponse
QueryDifficultyRequest, QueryDifficultyResponse

# Configuration types
Params, TierConfig
```

---

## Canonical Serialization Module

### Purpose

`canon.py` provides deterministic serialization of messages for signature verification. The user signs canonical bytes; the chain verifies using the same bytes. Any deviation causes signature verification failure.

### Critical Design Constraint

**The `authority` field (tag 1) is NOT included in canonical bytes.**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CANONICAL BYTES vs FULL MESSAGE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Full Protobuf Message:                                                      │
│    tag1: authority (validator address)  ← NOT in canonical bytes            │
│    tag2: envelope_pubkey                ← In canonical bytes                │
│    tag3: envelope_block_hash            ← In canonical bytes                │
│    tag4: envelope_difficulty            ← In canonical bytes                │
│    tag5: envelope_pow                   ← In canonical bytes (when present) │
│    tag6: envelope_timestamp             ← In canonical bytes                │
│    tag10: envelope_signature            ← NOT in canonical bytes            │
│    tag100+: payload fields              ← In canonical bytes                │
│                                                                              │
│  Canonical Bytes = prefix + tags 2-6 + tags 100+                            │
│                                                                              │
│  Why exclude authority?                                                      │
│    - Authority is the validator relaying the transaction                    │
│    - User doesn't know which validator will relay                           │
│    - Set by backend after user signs                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Serialization Format

Each message type has its own canonical builder:

```python
def canon_base_post(
    pubkey: bytes,
    last_block_hash: bytes,
    difficulty: int,
    timestamp: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str = "",
    pow_val: int = 0,
) -> bytes:
    out = bytearray(_prefix("MsgPost"))  # "mirage.core.v1:MsgPost\x00"
    out += _enc_bytes(2, pubkey)
    out += _enc_bytes(3, last_block_hash)
    out += _enc_u64(4, difficulty)
    if pow_val > 0:
        out += _enc_u64(5, pow_val)
    out += _enc_u64(6, timestamp)
    out += _enc_str(100, target)
    out += _enc_str(101, topic or "")
    out += _enc_str(102, title)
    out += _enc_str(103, content)
    out += _enc_str(104, tag)
    return bytes(out)
```

### Encoding Primitives

The module implements protobuf-compatible encoding:

```python
def uvarint(n: int) -> bytes:
    """Encode unsigned integer as variable-length integer."""
    n = int(n) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)

def _enc_str(tag: int, s: str) -> bytes:
    """Encode string field: tag + length + UTF-8 bytes."""
    b = (s or "").encode("utf-8")
    return _enc_tag(tag) + uvarint(len(b)) + b

def _enc_bytes(tag: int, b: bytes) -> bytes:
    """Encode bytes field: tag + length + raw bytes."""
    b = bytes(b or b"")
    return _enc_tag(tag) + uvarint(len(b)) + b
```

### PoW Insertion

The `canon_signed_with_pow` function inserts the PoW value into existing canonical bytes:

```python
def canon_signed_with_pow(base: bytes, pow_val: int) -> bytes:
    """
    Insert pow (tag 5) between difficulty (tag 4) and timestamp (tag 6).
    
    This is needed because:
    1. Base canonical bytes are built without PoW (for PoW computation)
    2. After computing PoW, the nonce is inserted
    3. Final bytes with PoW are signed
    """
    # Parse base bytes to find tag 4/6 boundary
    # Insert _enc_u64(5, pow_val) at that position
    # Return modified bytes
```

### Signed Integer Handling

Direction field in MsgVote is int32 (can be -1 for downvote):

```python
def canon_base_vote(pubkey, last_block_hash, difficulty, timestamp, target, direction):
    # ...
    # Direction is int32 in proto, but Go converts to uint32 before encoding
    # int32(-1) -> uint32(4294967295)
    dir_val = direction if direction >= 0 else (direction & 0xFFFFFFFF)
    out += _enc_u64(101, dir_val)
    return bytes(out)
```

---

## Configuration Module

### Purpose

`config.py` provides centralized configuration loading from the node HOME directory. All services read configuration from the same source, ensuring consistency.

### Design Philosophy

**No separate config files.** Configuration is derived from:
- `~/.mirage/node/config/client.toml` (chain ID, keyring)
- `~/.mirage/node/config/app.toml` (gRPC, REST, gas prices)
- `~/.mirage/node/config/config.toml` (RPC, P2P, consensus)
- `~/.mirage/node/config/genesis.json` (denoms, chain params)

```python
class MirageConfig:
    def __init__(self, config_path: Optional[str] = None):
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        home = os.path.join(Path.home() / ".mirage", "node")
        cfg_dir = os.path.join(home, "config")
        
        client_toml = _read_toml(os.path.join(cfg_dir, "client.toml"))
        app_toml = _read_toml(os.path.join(cfg_dir, "app.toml"))
        comet_toml = _read_toml(os.path.join(cfg_dir, "config.toml"))
        genesis = _read_json(os.path.join(cfg_dir, "genesis.json"))
        
        # Derive ports from laddr settings
        rpc_port = _port_from_laddr(comet_toml["rpc"]["laddr"])
        grpc_port = _port_from_addr(app_toml["grpc"]["address"])
        
        return {
            "chain_id": client_toml["chain-id"],
            "keyring_backend": client_toml["keyring-backend"],
            "ports": {"rpc": rpc_port, "grpc": grpc_port, ...},
            "economics": {"bond_denom": ..., "gas_price": ...},
        }
```

### Usage

```python
from shared.config import get_config

config = get_config()
rpc_port = config.get("ports", "rpc", default=26657)
chain_id = config.get("chain_id")
node_config = config.get_node_config()  # Returns URLs, paths
indexer_config = config.get_indexer_config()  # Returns DB URL, gRPC URL
```

### Indexer Configuration

The indexer configuration includes database URL from environment:

```python
def get_indexer_config(self) -> Dict[str, Any]:
    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        raise RuntimeError("INDEXER_DB_URL is required")
    return {
        "enabled": True,
        "jsonrpc_url": f"http://127.0.0.1:{rpc_port}",
        "grpc_url": f"127.0.0.1:{grpc_port}",
        "database_url": db_url,
        "reconnect": {"initial_delay": 1, "max_delay": 60, "max_retries": -1},
    }
```

### Database URL Helpers

`config.py` also provides helpers for the dual-database architecture:

```python
def get_indexer_db_url() -> str:       # INDEXER_DB_URL (indexer read-write)
def get_indexer_ro_url() -> str:       # INDEXER_DB_RO_URL (backend read-only)
def get_backend_db_url() -> str:       # BACKEND_DB_URL (backend read-write)
```

All three raise `RuntimeError` if the corresponding environment variable is missing or empty.

---

## Logging Setup Module

### Purpose

`logging_setup.py` provides consistent, structured logging across all Python services with:

- Date-based log rotation (one file per day, UTC)
- Console output for interactive visibility
- Exception hooks for crash capture
- Async exception handling

### Log Directory Structure

```
~/.mirage/logs/
├── node/           # miraged logs
├── indexer/        # indexer-YYYY-MM-DD.log
├── backend/        # backend-YYYY-MM-DD.log
├── postgres/       # postgres-YYYY-MM-DD.log
├── caddy/          # Web server logs
├── referrals/      # Referral daemon logs
└── deploy/         # Deployment logs
```

### Date-Based Handler

Custom file handler that automatically switches files at midnight UTC:

```python
class _DateFileHandler(logging.FileHandler):
    def __init__(self, log_dir: str, component: str, encoding: str = "utf-8"):
        self.log_dir = log_dir
        self.component = component
        self._current_date = self._get_utc_date()
        log_path = _get_date_log_path(log_dir, component)
        super().__init__(log_path, mode="a", encoding=encoding)

    def emit(self, record: logging.LogRecord) -> None:
        current_date = self._get_utc_date()
        if current_date != self._current_date:
            self._current_date = current_date
            self.close()
            self.baseFilename = _get_date_log_path(self.log_dir, self.component)
            self.stream = self._open()
        super().emit(record)
```

### Exception Capture

The module installs hooks to capture all exceptions:

```python
# Global exception hook
def _excepthook(exc_type, exc, tb):
    logging.getLogger().error(
        "FATAL: Unhandled exception",
        exc_info=(exc_type, exc, tb),
    )
sys.excepthook = _excepthook

# Thread exception hook (Python 3.8+)
def _thread_excepthook(args):
    logging.getLogger().error(
        f"FATAL: Unhandled exception in thread {args.thread.name}",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
threading.excepthook = _thread_excepthook

# Asyncio exception handler
def _asyncio_handler(loop, context):
    exc = context.get("exception")
    logging.getLogger().error("ASYNC ERROR: %s", msg, exc_info=exc)
```

### Usage

```python
from shared.logging_setup import configure_logging

# Call once at startup
log_path = configure_logging(
    component="indexer",
    level=logging.INFO,
    redirect_std=True  # Redirect stdout/stderr to logging
)
# Returns: ~/.mirage/logs/indexer/indexer-2026-01-21.log
```

---

## Client Module

### Purpose

`client.py` provides gRPC client utilities for querying the blockchain. It wraps common operations and handles connection management.

### Key Features

- Connection pooling for gRPC channels
- Retry logic for transient failures
- Typed query methods for common operations

---

## Cross-Language Consistency

### The Consistency Challenge

Three codebases must produce identical results:

| Language | Component | Critical Operations |
|----------|-----------|---------------------|
| Go | Blockchain | Canonical bytes, signature verification |
| Python | Backend/Indexer | Canonical bytes, message construction |
| JavaScript | Frontend | Canonical bytes, PoW computation |

### Ensuring Consistency

1. **Field Numbers** - All implementations use identical protobuf field numbers
2. **Byte Encoding** - uvarint encoding must match exactly
3. **Field Order** - Tags are always written in ascending order
4. **Empty Values** - Empty strings/bytes are still encoded (length=0)

### Testing Strategy

When canonical serialization changes:
1. Generate test vectors in Go (authoritative source)
2. Verify Python produces identical bytes
3. Verify JavaScript produces identical bytes

```python
# Test vector verification
def test_canonical_post():
    expected_hex = "..."  # From Go test
    actual = canon_base_post(
        pubkey=bytes.fromhex("..."),
        last_block_hash=bytes.fromhex("..."),
        difficulty=10,
        timestamp=1700000000000,
        target="",
        topic="general",
        title="Test",
        content="Hello",
        tag="",
    )
    assert actual.hex() == expected_hex
```

---

## Testing Considerations

### Unit Testing

Each module has testable components:

```python
# Test datatypes
def test_msg_post_creation():
    msg = MsgPost()
    msg.authority = "mirage1..."
    msg.envelope_pubkey = b"..."
    assert msg.SerializeToString()

# Test canonical bytes
def test_canon_vote_direction():
    # Upvote
    up = canon_base_vote(..., direction=1)
    # Downvote (should encode as uint32)
    down = canon_base_vote(..., direction=-1)
    assert down != up
```

### Integration Testing

End-to-end tests verify cross-language consistency:

1. Frontend signs message
2. Backend verifies signature
3. Chain accepts transaction
4. Indexer parses events

Any canonical serialization mismatch breaks the chain.

---

## Maintenance Notes

### Adding New Message Types

1. Add to Go `.proto` file
2. Add to `datatypes.py` (field definitions)
3. Add to `canon.py` (canonical builder)
4. Add to frontend `TransactionHandler.js` (if user-facing)
5. Add to backend routes (if relayed)
6. Add to indexer message processor (if indexed)

### Modifying Existing Messages

**Changing field numbers breaks signatures.** Never change field numbers for existing fields. Only add new fields with new numbers.

### Version Compatibility

Shared modules must maintain backward compatibility with:
- Running blockchain (can't change consensus-critical code without upgrade)
- Deployed frontend (users may have cached JavaScript)
- Indexer database schema (migrations required)
