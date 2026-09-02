#!/usr/bin/env python3
"""Drive one creator payout end to end against the local testnet.

The Go tests prove the accounting; this proves the whole stack agrees with it.
It buys a subscription, has that paying subscriber upvote somebody else's post,
waits for the epoch holding that upvote to close, and claims the reward.

Runs ONLY inside the local mirage container. Every wait has a deadline and the
script exits non-zero the moment an expectation is not met.
"""
from __future__ import annotations

import json
import socket
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/mirage")

from tests.common import (  # noqa: E402
    _b64,
    _faucet,
    _fetch_params,
    _fresh_nonce,
    _generate_wallet,
    _lb_bytes,
    _now_ms,
    _post,
    _do_subscribe,
)
from tests.backend_helpers import (  # noqa: E402
    _do_post,
    _do_set_username_raw,
    _do_vote,
    _rpc_latest_height,
    _wait_tx_deliver,
)
from shared.canon import (  # noqa: E402
    canon_base_claim_creator_rewards,
    canon_signed_with_pow,
)
from shared.client import compute_pow, sign_canonical  # noqa: E402

BACKEND = "http://127.0.0.1:80"
REST = "http://127.0.0.1:1317"
COMMUNITY = "payoutprobe"
SUBSCRIPTION_FUNDING = 200_000_000_000


def die(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def step(msg: str) -> None:
    print(f"\n=== {msg} ===")


def rest(path: str) -> dict:
    with urllib.request.urlopen(f"{REST}{path}", timeout=10) as r:
        return json.load(r)


def balance(addr: str) -> int:
    data = rest(f"/cosmos/bank/v1beta1/balances/{addr}")
    for c in data.get("balances", []):
        if c.get("denom") == "umirage":
            return int(c["amount"])
    return 0


def schedule() -> dict:
    s = rest("/mirage/core/v1/creator/schedule")
    return {
        "origin_epoch": int(s["origin_epoch"]),
        "origin_unix": int(s["origin_unix"]),
        "epoch_seconds": int(s["epoch_seconds"]),
        "current_epoch": int(s["current_epoch"]),
    }


def epoch_bounds(sched: dict, epoch: int) -> tuple[int, int]:
    start = sched["origin_unix"] + (epoch - sched["origin_epoch"]) * sched["epoch_seconds"]
    return start, start + sched["epoch_seconds"]


def creator_epoch(epoch: int) -> dict | None:
    try:
        return rest(f"/mirage/core/v1/creator/epoch/{epoch}").get("epoch")
    except Exception:
        return None


def commit(label: str, resp: dict, from_height: int) -> str:
    """Assert a relayed action reached the chain and succeeded there.

    The indexer's tx-status endpoint only carries details for content actions,
    so consensus is read from the block results instead.
    """
    resp = resp or {}
    if resp.get("error") or int(resp.get("code", 0) or 0) != 0:
        die(f"{label} rejected by backend: {resp}")
    tx_hash = str(resp.get("tx_hash", "") or "").lower()
    if not tx_hash:
        die(f"{label} returned no tx hash: {resp}")
    res = _wait_tx_deliver(tx_hash, timeout=120.0, from_height=from_height)
    if res is None:
        die(f"{label} tx {tx_hash} never appeared on chain")
    code, log = res
    if code != 0:
        die(f"{label} tx {tx_hash} failed on chain: code={code} log={log[:300]}")
    print(f"  {label} committed ({tx_hash})")
    return tx_hash


def wait_for_epoch_runway(min_seconds: int) -> tuple[dict, int]:
    """Return a schedule and epoch with at least min_seconds left to run.

    Without this the upvote could land a second either side of a boundary and
    the script would watch the wrong epoch.

    `current_epoch` is the chain's stored clock, which the node advances in
    BeginBlock once a boundary has passed, so just after a boundary it still
    reports the epoch that has already ended and `left` goes negative. Sleeping
    for that value spins, and then raises once it reaches -1.
    """
    deadline = time.time() + 900
    while time.time() < deadline:
        sched = schedule()
        epoch = sched["current_epoch"]
        _, end = epoch_bounds(sched, epoch)
        left = end - int(time.time())
        if left >= min_seconds:
            return sched, epoch
        print(f"  epoch {epoch} has only {left}s left; waiting for the next one")
        time.sleep(max(min(left + 2, 30), 2))
    die(f"no epoch offered {min_seconds}s of runway within 15 minutes")


def claim(wallet, epoch_ids: list[int]) -> dict:
    """Claim rewards for a free-tier author, which means real PoW."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(BACKEND, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    base = canon_base_claim_creator_rewards(pub, _lb_bytes(lb), diff, ts, epoch_ids, nonce)
    proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    sig = sign_canonical(wallet, canon_signed_with_pow(base, int(proof)))
    _, resp = _post(
        f"{BACKEND}/api/core/claim_creator_rewards",
        {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "epoch_ids": epoch_ids,
        },
    )
    return resp or {}


def main() -> int:
    if socket.gethostname().strip().lower() != "testnet":
        die("must run inside the local mirage container")

    sched = schedule()
    if sched["epoch_seconds"] != 300:
        die(f"expected a 300s payout interval, chain reports {sched['epoch_seconds']}")
    print(f"payout interval: {sched['epoch_seconds']}s  origin_epoch={sched['origin_epoch']}")

    step("provisioning an author and a paying subscriber")
    author = _generate_wallet()
    subscriber = _generate_wallet()
    author_addr = str(author.address())
    sub_addr = str(subscriber.address())
    print(f"author     {author_addr}")
    print(f"subscriber {sub_addr}")

    if not _faucet(BACKEND, author_addr, 5_000_000_000):
        die("faucet to author failed")
    if not _faucet(BACKEND, sub_addr, SUBSCRIPTION_FUNDING):
        die("faucet to subscriber failed")

    # Subscribing requires a profile, so the username has to be committed
    # before the fee is simulated, not merely broadcast.
    suffix = str(int(time.time()))[-6:]
    for wallet, name in ((author, f"payoutauthor{suffix}"), (subscriber, f"payoutsub{suffix}")):
        h0 = _rpc_latest_height()
        commit(f"set_username {name}", _do_set_username_raw(BACKEND, wallet, name), h0)

    step("buying a subscription (this is what funds the pool)")
    liability_before = int(rest("/mirage/core/v1/creator/liability")["liability"])
    h0 = _rpc_latest_height()
    commit("subscribe", _do_subscribe(BACKEND, subscriber, 1), h0)
    liability_after = int(rest("/mirage/core/v1/creator/liability")["liability"])
    print(f"creator liability {liability_before} -> {liability_after} (+{liability_after - liability_before})")
    if liability_after <= liability_before:
        die("subscription did not book any creator liability")
    prof = rest(f"/mirage/core/v1/profile/{sub_addr}")
    if not prof.get("effective_paid"):
        die("subscriber is not effective_paid, so its upvote would not count")
    print(f"subscriber effective_paid=True level={prof.get('level')}")

    step("author posts")
    h0 = _rpc_latest_height()
    post_tx = _do_post(BACKEND, author, COMMUNITY, "Five minute payout probe", "Testing creator rewards.")
    if not post_tx:
        die("post rejected by backend")
    res = _wait_tx_deliver(post_tx, timeout=120.0, from_height=h0)
    if res is None or res[0] != 0:
        die(f"post tx {post_tx} did not commit cleanly: {res}")
    print(f"  post committed ({post_tx})")

    step("paying subscriber upvotes it")
    sched, engaged_epoch = wait_for_epoch_runway(120)
    start, end = epoch_bounds(sched, engaged_epoch)
    print(f"  targeting epoch {engaged_epoch} (window {start}..{end}, {end - int(time.time())}s left)")
    h0 = _rpc_latest_height()
    vote_tx = commit("upvote", _do_vote(BACKEND, subscriber, post_tx, 1), h0)
    landed = schedule()["current_epoch"]
    if landed != engaged_epoch:
        die(f"upvote straddled a boundary: targeted {engaged_epoch}, chain now at {landed}")
    print(f"  upvote {vote_tx} is recorded in epoch {engaged_epoch}")

    step(f"waiting for epoch {engaged_epoch} to close and settle")
    deadline = end + 240
    seen = None
    while time.time() < deadline:
        ce = creator_epoch(engaged_epoch)
        if ce:
            status = ce.get("status")
            if status != seen:
                print(
                    f"  t+{int(time.time() - start)}s status={status} "
                    f"pool={ce.get('pool')} engagers={ce.get('active_engagers')} "
                    f"allocated={ce.get('allocated_total')}"
                )
                seen = status
            if status == "CREATOR_EPOCH_STATUS_CLAIMABLE":
                break
            if status == "CREATOR_EPOCH_STATUS_EXPIRED":
                die(f"epoch {engaged_epoch} expired instead of becoming claimable")
        time.sleep(5)
    else:
        die(f"epoch {engaged_epoch} did not become claimable before {deadline}")

    ce = creator_epoch(engaged_epoch)
    pool = int(ce["pool"])
    print(f"epoch {engaged_epoch} CLAIMABLE pool={pool} allocated={ce['allocated_total']}")
    print(f"  window start_unix={ce['start_unix']} end_unix={ce['end_unix']} (span {int(ce['end_unix']) - int(ce['start_unix'])}s)")
    print(f"  claim_deadline_unix={ce['claim_deadline_unix']}")
    if pool <= 0:
        die("epoch became claimable with an empty pool")
    if int(ce["end_unix"]) - int(ce["start_unix"]) != 300:
        die("a full epoch must span exactly the payout interval")
    if int(ce["claim_deadline_unix"]) - int(ce["end_unix"]) < 29 * 86400:
        die("claim window is shorter than the 30 days the chain promises")

    step("author's accrual")
    accruals = rest(f"/mirage/core/v1/creator/epoch/{engaged_epoch}/accruals").get("accruals", [])
    mine = [a for a in accruals if a.get("creator") == author_addr]
    if not mine:
        die(f"author earned nothing; accruals={accruals}")
    earned = int(mine[0]["amount"])
    print(f"author earned {earned} umirage ({earned / 1e6:.6f} MIRAGE)")
    if earned <= 0:
        die("accrual is zero")
    if mine[0]["claimed"]:
        die("accrual is already marked claimed")

    step("claiming")
    before = balance(author_addr)
    h0 = _rpc_latest_height()
    commit("claim", claim(author, [engaged_epoch]), h0)
    after = balance(author_addr)
    print(f"author balance {before} -> {after} (+{after - before})")
    if after - before != earned:
        die(f"paid {after - before}, expected exactly {earned}")

    ce = creator_epoch(engaged_epoch)
    print(f"epoch claimed_total now {ce['claimed_total']}")
    if int(ce["claimed_total"]) < earned:
        die("epoch did not record the claim")

    resp = claim(author, [engaged_epoch])
    if not (resp.get("error") or int(resp.get("code", 0) or 0) != 0):
        die("a second claim for the same epoch must be rejected")
    print(f"double claim correctly rejected: {str(resp.get('error') or resp.get('raw_log'))[:120]}")

    print(f"\nPASS: 5-minute payout worked end to end (epoch {engaged_epoch}, {earned} umirage claimed)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # surface the failure, never mask it
        print(f"FAIL: {exc!r}")
        raise SystemExit(1)
