"""Chain-level checks for the network tag memo (v1.36.1).

The backend attaches the tag as TxBody.memo. Nothing about that is enforced by
chain code — there is deliberately no ValidateMemoDecorator in the relay ante
chain — which is precisely why the chain's side of the contract needs a test:
the feature quietly depends on the chain accepting a memo-bearing relay tx,
charging for it, and handing it back byte-identical.

What breaks without each of these:

  * Acceptance. If any ante decorator rejected a memo, every relayed post on
    the network would begin failing at once the moment the backend deploys.
  * Round trip. If the memo did not survive signing and commit, agents would
    read nothing, and the failure would look like "the backend isn't tagging"
    rather than "the chain dropped it".
  * The full budget. The memo is ~101 bytes today but the format has room to
    grow to 256. Proving the ceiling is accepted now means a later field
    addition cannot silently cross a limit nobody tested.
"""

from __future__ import annotations

import base64
import hashlib
import json

import requests

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _rand_str,
    _now_ms,
    WALLETS,
)
from tests.blockchain_helpers import (
    COMET_RPC_URL,
    DEFAULT_GAS_LIMIT,
    _build_msg_post,
    _shared_community,
    _gen_nonce,
    _get_pow_params,
    _get_validator_account_address,
    _submit_tx,
)
from shared.nettag import (
    MEMO_MAX_BYTES,
    NAMESPACE_BYTES,
    NET_CLASSES,
    STATUS_VALID,
    TAG_BYTES,
    b64u_encode,
    encode_memo,
    parse_memo,
)

def _committed_memo(tx_hash: str, lookback: int = 20) -> str | None:
    """Read the memo back out of the block the transaction was committed in.

    Deliberately not via /tx: this node runs with tx_index disabled, and going
    through an index would prove only that the index kept the memo. Decoding the
    raw bytes out of block data is the same thing an agent following the chain
    does, and it is the only evidence that the memo is really in consensus.
    """
    from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, TxRaw

    want = tx_hash.strip().upper().removeprefix("0X")
    try:
        status = requests.get(f"{COMET_RPC_URL}/status", timeout=5).json()
        tip = int(status["result"]["sync_info"]["latest_block_height"])
    except Exception as e:
        _debug(f"net_tags_chain: status query failed: {e}")
        return None

    for height in range(tip, max(1, tip - lookback), -1):
        try:
            block = requests.get(f"{COMET_RPC_URL}/block", params={"height": height}, timeout=5).json()
        except Exception:
            continue
        txs = (((block or {}).get("result") or {}).get("block") or {}).get("data", {}).get("txs") or []
        for tx_b64 in txs:
            raw_bytes = base64.b64decode(tx_b64)
            if hashlib.sha256(raw_bytes).hexdigest().upper() != want:
                continue
            tx_raw = TxRaw()
            tx_raw.ParseFromString(raw_bytes)
            body = TxBody()
            body.ParseFromString(tx_raw.body_bytes)
            _debug(f"net_tags_chain: found {want[:12]} in block {height}")
            return body.memo
    return None


def _post_with_memo(backend: str, wallet, memo: str, label: str):
    """Submit one relay post carrying `memo`. Returns (tx_hash, deliver_code)."""
    lb, diff, _bits, _factor = _get_pow_params(backend, str(wallet.address()))
    msg = _build_msg_post(
        wallet,
        lb,
        diff,
        _now_ms(),
        _shared_community(),
        "Network tag memo",
        f"chain-level memo check {label}",
        pow_val=0,
        nonce=_gen_nonce(),
    )
    tx_hash, check_code, check_log, deliver_code, deliver_log = _submit_tx(
        [(msg, "/mirage.core.v1.MsgPost")],
        DEFAULT_GAS_LIMIT,
        _get_validator_account_address(backend),
        wallet.public_key().public_key_bytes,
        wait_deliver=True,
        memo=memo,
    )
    if check_code != 0:
        _fail(f"net_tags_chain.{label}", f"CheckTx rejected the memo: code={check_code} log={check_log}")
        return None, None
    if deliver_code != 0:
        _fail(f"net_tags_chain.{label}", f"DeliverTx rejected the memo: code={deliver_code} log={deliver_log}")
        return None, None
    return tx_hash, deliver_code


def _sample_memo(net_class: str | None = "hosting") -> str:
    return encode_memo(
        b64u_encode(bytes(range(NAMESPACE_BYTES))),
        "2026-W34",
        4,
        b64u_encode(bytes(range(TAG_BYTES))),
        net_class,
    )


def test_net_tags_chain(backend: str) -> None:
    """A relay tx carrying a network tag memo is accepted and round-trips."""
    _debug("net_tags_chain: start")

    wallet = WALLETS.get("sub1")
    if wallet is None:
        _skip("net_tags_chain.setup", "sub1 wallet not available")
        return

    # 1. A realistic tag memo is accepted and comes back byte-identical.
    memo = _sample_memo()
    tx_hash, _ = _post_with_memo(backend, wallet, memo, "accepted")
    if tx_hash is None:
        return
    _pass("net_tags_chain.accepted", bytes=len(memo.encode("ascii")))

    committed = _committed_memo(tx_hash)
    if committed is None:
        _fail("net_tags_chain.round_trip", f"could not read tx {tx_hash[:12]} back from the chain")
    elif committed != memo:
        _fail("net_tags_chain.round_trip", f"memo changed in flight: sent {memo!r}, chain has {committed!r}")
    else:
        _pass("net_tags_chain.round_trip")
        # The committed bytes must still parse, which is what an agent does.
        parsed = parse_memo(committed)
        if parsed.status != STATUS_VALID:
            _fail("net_tags_chain.committed_memo_parses", f"{parsed.status}: {parsed.reason}")
        else:
            _pass("net_tags_chain.committed_memo_parses", epoch=parsed.epoch, net_class=parsed.net_class)

    # 2. The full 256-byte budget is accepted, not just today's ~101 bytes.
    #    Padded through the class field so the result is still a legal memo
    #    shape rather than arbitrary bytes the ante might treat differently.
    longest = _sample_memo(max(NET_CLASSES, key=len))
    filler = MEMO_MAX_BYTES - len(longest.encode("ascii"))
    if filler < 0:
        _fail("net_tags_chain.max_budget", f"largest legal memo already exceeds {MEMO_MAX_BYTES}")
    else:
        padded = json.dumps(
            {"nettag": json.loads(longest)["nettag"], "pad": "x" * max(0, filler - len(',"pad":""'))},
            separators=(",", ":"),
        )
        padded = padded[:MEMO_MAX_BYTES]
        tx_hash_max, _ = _post_with_memo(backend, wallet, padded, "max_budget")
        if tx_hash_max is not None:
            _pass("net_tags_chain.max_budget", bytes=len(padded.encode("ascii")))

    # 3. Control: the same message shape without a memo. Isolates the memo as
    #    the only variable, so a failure above cannot be blamed on unrelated
    #    breakage in the relay post path.
    empty_hash, _ = _post_with_memo(backend, wallet, "", "untagged_control")
    if empty_hash is not None:
        _pass("net_tags_chain.untagged_still_accepted")

    _debug("net_tags_chain: done")
