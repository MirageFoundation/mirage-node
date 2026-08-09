"""
Reward Distributor

Handles distribution of MIRAGE token rewards from the rewards pool to users.

Configuration (via environment variables):
- QUESTS_REWARDS_POOL_ADDRESS: The address holding reward tokens
- QUESTS_PAYOUTS_ENABLED: Set to "true" to enable actual token transfers

When QUESTS_PAYOUTS_ENABLED is false, rewards are logged but not sent.
This allows testing the full flow without requiring a funded rewards pool.

To set up the rewards pool:
1. Add key from seed phrase:
   miraged keys add rewards_pool --recover --keyring-backend test
2. Get the address:
   miraged keys show rewards_pool --keyring-backend test -a
3. Fund the address (governance proposal or direct transfer)
4. Set QUESTS_REWARDS_POOL_ADDRESS and QUESTS_PAYOUTS_ENABLED=true in environment

Payouts are a two-phase state machine (M-1 in the 2026-08-06 review). A claim
first reserves the reward rows and persists the exact signed tx bytes, hash and
unordered timeout in `reward_payouts`, and only then broadcasts. A crash at any
point leaves a durable record: the next claim reconciles it by hash instead of
paying again, and rows are released only when the tx is definitively dead.
"""

from __future__ import annotations

import hashlib
import logging
import math
import secrets
import time
from typing import List, Optional, Tuple

from bech32 import bech32_decode  # type: ignore

from db import connect_backend_db, connect_db
from quest_multiplier import get_reward_multiplier


def is_valid_mirage_address(address: str) -> bool:
    """True only for a well-formed mirage1 bech32 account address.

    The recipient ends up in a signed bank send, so it is validated before any
    tx bytes are built (L-6).
    """
    addr = str(address or "").strip()
    if not addr or addr != addr.lower():
        return False
    hrp, data = bech32_decode(addr)
    return hrp == "mirage" and bool(data)


def get_balance(address) -> int:
    """Read balance from indexer DB."""
    if not address:
        return 0
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance FROM balances WHERE address = LOWER(%s)", (str(address),))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


from node import require_runtime
from settings import QUESTS_PAYOUTS_ENABLED, QUESTS_REWARDS_POOL_ADDRESS
from tx import (
    bank_send_body_bytes,
    broadcast_tx,
    build_signed_tx,
    chain_head,
    estimate_total_gas_limit,
    resolve_tx_by_scan,
    simulate_gas,
)

logger = logging.getLogger(__name__)

# Characters for invite codes (uppercase alphanumeric, excluding confusing chars)
INVITE_CODE_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # Excludes I, O, 0, 1 for clarity


def _generate_invite_code() -> str:
    """Generate a random invite code in format XXXX-XXXX."""
    # secrets (CSPRNG) — invite codes are bearer credentials when the feature is on.
    # If REGISTRATION_INVITE_CODE_REQUIRED is ever turned back on, this must stay.
    part1 = "".join(secrets.choice(INVITE_CODE_CHARS) for _ in range(4))
    part2 = "".join(secrets.choice(INVITE_CODE_CHARS) for _ in range(4))
    return f"{part1}-{part2}"


def _generate_unique_invite_codes(cur, owner: str, count: int) -> List[str]:
    """Generate unique invite codes on the caller's cursor.

    Runs inside the claim transaction so codes and the `claimed_at` update
    commit together: a rollback must not leave issued codes behind.
    """
    codes: List[str] = []
    now_ts = int(time.time())

    cur.execute("SELECT code FROM invite_codes")
    existing = {row[0] for row in cur.fetchall()}

    for _ in range(count):
        for _attempt in range(100):
            code = _generate_invite_code()
            if code not in existing:
                break
        else:
            raise RuntimeError("failed to generate a unique invite code after 100 attempts")

        existing.add(code)
        codes.append(code)

        cur.execute(
            """
            INSERT INTO invite_codes (code, owner, created_at)
            VALUES (%s, %s, %s)
            """,
            (code, owner, now_ts),
        )
        logger.info(f"Generated invite code {code} for {owner}")

    return codes


# CheckTx rejections that prove the tx never entered a mempool, so the reserved
# reward rows can be released back to the user.
_DEFINITIVE_REJECT_CODES = {
    2,  # tx decode error
    4,  # unauthorized
    5,  # insufficient funds
    9,  # unknown address
    11,  # out of gas at CheckTx
    13,  # insufficient fee
    30,  # tx timeout height / unordered timeout exceeded
}
# Simulation underestimates DeliverTx; same buffer the relay path uses.
_PAYOUT_GAS_BUFFER = 1.25


class InsufficientPoolBalance(RuntimeError):
    pass


class RewardDistributor:
    """
    Distributes MIRAGE token rewards to users.

    Operates in two modes:
    - Dry run (default): Logs would-be transfers, marks rewards as claimed
    - Live mode: Actually sends tokens from the rewards pool
    """

    def __init__(self, pool_address: Optional[str] = None, enabled: Optional[bool] = None):
        """
        Initialize the reward distributor.

        Args:
            pool_address: Override rewards pool address (uses env var if not provided)
            enabled: Override enabled flag (uses env var if not provided)
        """
        self.pool_address = pool_address or QUESTS_REWARDS_POOL_ADDRESS
        self.enabled = enabled if enabled is not None else QUESTS_PAYOUTS_ENABLED

        if self.enabled and not self.pool_address:
            raise RuntimeError("payouts enabled without a rewards pool address")

    def is_configured(self) -> bool:
        """Check if the distributor is properly configured to send rewards."""
        return self.enabled and bool(self.pool_address)

    def get_pool_balance(self) -> int:
        """Get the current balance of the rewards pool."""
        if not self.pool_address:
            return 0
        return get_balance(self.pool_address)

    def can_send(self, amount: int) -> bool:
        """Check if the pool has sufficient balance to send the amount."""
        if not self.enabled:
            return True  # Dry run always succeeds
        return self.get_pool_balance() >= amount

    def build_payout_tx(self, recipient: str, amount: int) -> Tuple[bytes, str, int, int]:
        """Sign an unordered bank send from the pool.

        Returns (tx_bytes, tx_hash, timeout_at, scan_height). Nothing is
        broadcast here — the caller persists these bytes first so a retry can
        rebroadcast the exact same tx, which the chain accepts at most once, and
        `scan_height` bounds where reconciliation has to look for it.
        """
        rt = require_runtime()
        if not rt.rewards_pool_privkey_bytes or not rt.rewards_pool_pubkey_bytes:
            raise RuntimeError("rewards pool signer not loaded")
        if rt.rewards_pool_addr != self.pool_address:
            raise RuntimeError(f"rewards pool signer {rt.rewards_pool_addr} does not match pool {self.pool_address}")
        if not is_valid_mirage_address(recipient):
            raise RuntimeError("invalid_recipient_address")
        if int(amount) <= 0:
            raise RuntimeError("payout amount must be > 0")

        body_bytes = bank_send_body_bytes(rt.rewards_pool_addr, recipient, int(amount))
        signer = {
            "privkey_bytes": rt.rewards_pool_privkey_bytes,
            "pubkey_bytes": rt.rewards_pool_pubkey_bytes,
            "account_number": int(rt.rewards_pool_account_number),
        }
        gas_est = int(estimate_total_gas_limit(body_bytes, len(recipient)))
        minimum_required = int(amount) + int(math.ceil(gas_est * rt.min_gas_price_umirage))
        if self.get_pool_balance() < minimum_required:
            raise InsufficientPoolBalance(
                f"pool balance does not cover amount plus estimated fee: required={minimum_required}"
            )
        probe_bytes, _ = build_signed_tx(body_bytes, gas_est, **signer)
        gas_used = int(simulate_gas(probe_bytes))
        gas_limit = max(gas_est, int(gas_used * _PAYOUT_GAS_BUFFER))
        required = int(amount) + int(math.ceil(gas_limit * rt.min_gas_price_umirage))
        if self.get_pool_balance() < required:
            raise InsufficientPoolBalance(f"pool balance does not cover amount plus fee: required={required}")
        # Read the head before signing: the tx cannot appear in an earlier block.
        scan_height, _head_time = chain_head()
        tx_bytes, timeout_ns = build_signed_tx(body_bytes, gas_limit, **signer)
        tx_hash = hashlib.sha256(tx_bytes).hexdigest().upper()
        timeout_at = int(math.ceil(timeout_ns / 1_000_000_000))
        logger.info(
            "payout.tx.built recipient=%s amount=%d gas_limit=%d tx_hash=%s timeout_at=%d scan_height=%d",
            recipient,
            amount,
            gas_limit,
            tx_hash,
            timeout_at,
            scan_height,
        )
        return tx_bytes, tx_hash, timeout_at, scan_height

    def reconcile_owner_payouts(self, owner: str) -> Optional[dict]:
        """Resolve every open payout for an owner.

        Returns the payout that is still in flight, or None when all of the
        owner's payouts reached a terminal state.
        """
        owner_lc = (owner or "").strip().lower()
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, amount, status, tx_hash, tx_bytes, timeout_at, scan_height
                    FROM reward_payouts
                    WHERE owner = %s AND status IN ('reserved', 'broadcast')
                    ORDER BY id
                    """,
                    (owner_lc,),
                )
                rows = cur.fetchall()

        unresolved: Optional[dict] = None
        for payout_id, amount, status, tx_hash, tx_bytes, timeout_at, scan_height in rows:
            state = self._reconcile_payout(
                int(payout_id), str(tx_hash), bytes(tx_bytes), int(timeout_at), int(scan_height)
            )
            logger.info("payout.reconcile id=%d was=%s now=%s hash=%s", payout_id, status, state, tx_hash)
            if state == "pending":
                unresolved = {"payout_id": int(payout_id), "tx_hash": str(tx_hash), "amount": int(amount)}
        return unresolved

    def _reconcile_payout(
        self, payout_id: int, tx_hash: str, tx_bytes: bytes, timeout_at: int, scan_height: int
    ) -> str:
        """Drive one payout toward a terminal state. Returns confirmed/failed/pending."""
        try:
            verdict, code, scanned_to = resolve_tx_by_scan(tx_hash, scan_height, timeout_at)
        except RuntimeError as e:
            # Ambiguous: the chain may or may not hold this tx. Never release.
            logger.error("payout.reconcile.scan_failed id=%d hash=%s err=%s", payout_id, tx_hash, e)
            return "pending"

        # `scan_height` is the next block to inspect, not the last one already
        # checked, so retries do not re-fetch the previous head forever.
        self._advance_scan(payout_id, scanned_to + 1)

        if verdict == "found":
            if code == 0:
                self._settle_payout(payout_id, "confirmed", None)
                logger.info("payout.confirmed id=%d hash=%s", payout_id, tx_hash)
                return "confirmed"
            # Included but rejected in execution: no tokens moved, and the
            # unordered nonce is spent, so this tx can never pay out.
            self._settle_payout(payout_id, "failed", f"chain_code_{code}")
            return "failed"

        if verdict == "expired":
            self._settle_payout(payout_id, "failed", "expired_not_found")
            return "failed"

        try:
            _hash, code, _height, raw_log = broadcast_tx(tx_bytes)
        except RuntimeError as e:
            logger.error("payout.reconcile.rebroadcast_failed id=%d hash=%s err=%s", payout_id, tx_hash, e)
            return "pending"
        # This may be a rebroadcast after the original HTTP response was lost.
        # A peer could still hold the tx even if this node now rejects it, so
        # only chain inclusion or expiry may release the rewards.
        state = self._apply_broadcast_result(
            payout_id,
            tx_hash,
            int(code),
            raw_log,
            release_definitive=False,
        )
        return "pending" if state == "broadcast" else state

    def _advance_scan(self, payout_id: int, scanned_to: int) -> None:
        """Move the reconciliation cursor forward so a retry re-reads less."""
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE reward_payouts SET scan_height = GREATEST(scan_height, %s) WHERE id = %s",
                    (int(scanned_to), payout_id),
                )

    def _apply_broadcast_result(
        self,
        payout_id: int,
        tx_hash: str,
        code: int,
        raw_log: str,
        *,
        release_definitive: bool = True,
    ) -> str:
        """Map a CheckTx result onto the payout state. Returns broadcast/failed/pending."""
        if code == 0 or "tx already exists in cache" in raw_log.lower():
            self._mark_broadcast(payout_id)
            return "broadcast"
        if release_definitive and int(code) in _DEFINITIVE_REJECT_CODES:
            self._settle_payout(payout_id, "failed", f"checktx_code_{code}: {raw_log[:200]}")
            return "failed"
        # Unknown rejection: the tx might still be in someone's mempool.
        logger.error("payout.broadcast.ambiguous id=%d hash=%s code=%d log=%s", payout_id, tx_hash, code, raw_log[:200])
        return "pending"

    def _mark_broadcast(self, payout_id: int) -> None:
        now = int(time.time())
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE reward_payouts
                    SET status = 'broadcast', attempts = attempts + 1, updated_at = %s
                    WHERE id = %s AND status IN ('reserved', 'broadcast')
                    """,
                    (now, payout_id),
                )

    def _settle_payout(self, payout_id: int, status: str, error: Optional[str]) -> None:
        """Move a payout to a terminal state, releasing rows only on failure."""
        if status not in ("confirmed", "failed"):
            raise RuntimeError(f"invalid terminal payout status: {status}")
        now = int(time.time())
        released = 0
        with connect_backend_db() as conn:
            prev_autocommit = conn.autocommit
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE reward_payouts
                        SET status = %s, error = %s, updated_at = %s
                        WHERE id = %s AND status IN ('reserved', 'broadcast')
                        """,
                        (status, error, now, payout_id),
                    )
                    if cur.rowcount == 1 and status == "failed":
                        cur.execute(
                            """
                            UPDATE pending_rewards
                            SET claimed_at = NULL, payout_amount = NULL, payout_batch_id = NULL
                            WHERE payout_batch_id = %s AND reward_type = 'mirage'
                            """,
                            (payout_id,),
                        )
                        released = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = prev_autocommit
        if status == "failed":
            logger.error("payout.failed id=%d error=%s released_rows=%d", payout_id, error, released)

    def claim_rewards(self, owner: str, ts: int) -> dict:
        """
        Process a reward claim for a user.

        This is called from the /api/rewards/claim endpoint.

        Phase 1 reserves: under a per-owner pg_advisory_xact_lock it marks the
        rows claimed, grants cosmetics/invite codes, and persists the signed
        payout. Phase 2 broadcasts the persisted bytes. Anything that leaves the
        payment ambiguous returns `payout_pending` and is retried by hash on the
        next claim; only a definitively dead tx releases the rows.

        Args:
            owner: User address
            ts: Current timestamp

        Returns:
            dict with:
            - success: bool
            - rewards: list of claimed rewards
            - tx_hash: str or None (for MIRAGE rewards)
            - error: str or None
        """
        owner_lc = (owner or "").strip().lower()
        if not is_valid_mirage_address(owner_lc):
            logger.warning("claim rejected malformed owner: %r", str(owner)[:64])
            return {"success": False, "rewards": [], "tx_hash": None, "error": "invalid_recipient_address"}

        if self.enabled:
            unresolved = self.reconcile_owner_payouts(owner_lc)
            if unresolved is not None:
                logger.warning("claim blocked by unresolved payout id=%s", unresolved["payout_id"])
                return {
                    "success": False,
                    "rewards": [],
                    "tx_hash": unresolved["tx_hash"],
                    "error": "payout_pending",
                }

        result, payout = self._reserve_claim(owner_lc, ts)
        if not result["success"] or payout is None:
            return result

        payout_id, tx_bytes, tx_hash = payout
        try:
            _hash, code, _height, raw_log = broadcast_tx(tx_bytes)
        except RuntimeError as e:
            logger.error("payout.broadcast.transport_failed id=%d hash=%s err=%s", payout_id, tx_hash, e)
            return {"success": False, "rewards": [], "tx_hash": tx_hash, "error": "payout_pending"}

        state = self._apply_broadcast_result(payout_id, tx_hash, int(code), raw_log)
        # BROADCAST_MODE_SYNC only reports CheckTx. Tokens have not moved until
        # reconciliation finds a successful DeliverTx in a committed block.
        error_code = "payout_failed" if state == "failed" else "payout_pending"
        return {"success": False, "rewards": [], "tx_hash": tx_hash, "error": error_code}

    def _reserve_claim(self, owner_lc: str, ts: int) -> Tuple[dict, Optional[Tuple[int, bytes, str]]]:
        """Phase 1: claim the rows and persist the signed payout, atomically.

        Returns (result, payout) where payout is (payout_id, tx_bytes, tx_hash)
        when a token transfer still has to be broadcast.
        """
        with connect_backend_db() as conn:
            # xact advisory locks require a real transaction; the helper opens
            # autocommit connections.
            prev_autocommit = conn.autocommit
            conn.autocommit = False
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (owner_lc,),
                    )
                    cur.execute(
                        """
                        SELECT id, reward_type, reward_data, reason
                        FROM pending_rewards
                        WHERE LOWER(owner) = LOWER(%s) AND claimed_at IS NULL
                        ORDER BY id
                        """,
                        (owner_lc,),
                    )
                    rows = cur.fetchall()

                if not rows:
                    conn.commit()
                    return (
                        {
                            "success": False,
                            "rewards": [],
                            "tx_hash": None,
                            "error": "no_rewards",
                        },
                        None,
                    )

                # Separate by type
                mirage_rewards = []
                invite_code_rewards = []
                cosmetic_rewards = []
                total_mirage_with_multiplier = 0
                total_mirage_no_multiplier = 0

                for row in rows:
                    reward_id, reward_type, reward_data, reason = row
                    reward_data = reward_data if isinstance(reward_data, dict) else {}

                    if reward_type == "mirage":
                        amount = reward_data.get("amount", 0)
                        apply_multiplier = reward_data.get("apply_multiplier", True)
                        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                            raise RuntimeError(f"invalid MIRAGE reward amount id={reward_id}: {amount!r}")
                        if not isinstance(apply_multiplier, bool):
                            raise RuntimeError(
                                f"invalid MIRAGE reward apply_multiplier id={reward_id}: {apply_multiplier!r}"
                            )
                        if apply_multiplier:
                            total_mirage_with_multiplier += amount
                        else:
                            total_mirage_no_multiplier += amount
                        mirage_rewards.append(
                            {
                                "id": reward_id,
                                "amount": amount,
                                "reason": reason,
                                "apply_multiplier": apply_multiplier,
                            }
                        )
                    elif reward_type == "invite_code":
                        count = reward_data.get("amount", 1)
                        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                            raise RuntimeError(f"invalid invite-code reward amount id={reward_id}: {count!r}")
                        invite_code_rewards.append(
                            {
                                "id": reward_id,
                                "amount": count,
                                "reason": reason,
                            }
                        )
                    else:
                        cosmetic_rewards.append(
                            {
                                "id": reward_id,
                                "type": reward_type,
                                "data": reward_data,
                                "reason": reason,
                            }
                        )

                # Get reward multiplier and compute payout
                multiplier = self._get_multiplier(owner_lc, ts)
                # Apply multiplier only to rewards that allow it
                payout_amount = int(total_mirage_with_multiplier * multiplier) + total_mirage_no_multiplier
                total_mirage = total_mirage_with_multiplier + total_mirage_no_multiplier
                reward_payouts = {
                    reward["id"]: (
                        int(reward["amount"] * multiplier) if reward["apply_multiplier"] else int(reward["amount"])
                    )
                    for reward in mirage_rewards
                }
                rounding_remainder = payout_amount - sum(reward_payouts.values())
                if rounding_remainder:
                    first_multiplied = next(
                        (reward for reward in mirage_rewards if reward["apply_multiplier"]),
                        None,
                    )
                    if first_multiplied is None:
                        raise RuntimeError(f"payout rounding mismatch without multiplied reward owner={owner_lc}")
                    reward_payouts[first_multiplied["id"]] += rounding_remainder

                result = {
                    "success": True,
                    "rewards": [],
                    "tx_hash": None,
                    "error": None,
                }

                # Reserve the MIRAGE payout while the advisory lock is held so a
                # concurrent claim waits and then finds nothing unclaimed.
                payout: Optional[Tuple[int, bytes, str]] = None
                payout_id: Optional[int] = None
                if mirage_rewards and payout_amount > 0:
                    if self.enabled:
                        try:
                            tx_bytes, tx_hash, timeout_at, scan_height = self.build_payout_tx(
                                owner_lc,
                                payout_amount,
                            )
                        except InsufficientPoolBalance as exc:
                            logger.warning(
                                "insufficient pool balance for %s: %s",
                                owner_lc,
                                exc,
                            )
                            conn.rollback()
                            return (
                                {
                                    "success": False,
                                    "rewards": [],
                                    "tx_hash": None,
                                    "error": "insufficient_pool_balance",
                                },
                                None,
                            )
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO reward_payouts
                                    (owner, amount, status, tx_hash, tx_bytes, timeout_at, scan_height,
                                     attempts, error, created_at, updated_at)
                                VALUES (%s, %s, 'reserved', %s, %s, %s, %s, 0, NULL, %s, %s)
                                RETURNING id
                                """,
                                (owner_lc, payout_amount, tx_hash, tx_bytes, timeout_at, scan_height, ts, ts),
                            )
                            payout_id = int(cur.fetchone()[0])
                        payout = (payout_id, tx_bytes, tx_hash)
                        result["tx_hash"] = tx_hash
                    else:
                        logger.info(
                            "[PAYOUTS DISABLED] would send %d umirage to %s from %s",
                            payout_amount,
                            owner_lc,
                            self.pool_address or "NO_POOL",
                        )

                    result["rewards"].append(
                        {
                            "type": "mirage",
                            "amount": payout_amount,
                            "raw_amount": total_mirage,
                            "multiplier": round(multiplier, 4),
                        }
                    )

                # Process cosmetic rewards
                for cosmetic in cosmetic_rewards:
                    unlock_type = cosmetic["type"]
                    unlock_id = cosmetic["data"].get("id")

                    if unlock_id:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO user_unlocks (owner, unlock_type, unlock_id, unlocked_at, source)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (owner, unlock_type, unlock_id) DO NOTHING
                                """,
                                (owner_lc, unlock_type, unlock_id, ts, cosmetic["reason"]),
                            )

                    result["rewards"].append(
                        {
                            "type": unlock_type,
                            "id": unlock_id,
                        }
                    )

                # Process invite code rewards
                for invite_reward in invite_code_rewards:
                    count = invite_reward.get("amount", 1)
                    with conn.cursor() as cur:
                        codes = _generate_unique_invite_codes(cur, owner_lc, count)
                    result["rewards"].append(
                        {
                            "type": "invite_code",
                            "codes": codes,
                            "count": len(codes),
                        }
                    )

                # Mark all rewards as claimed and store payout amounts
                mirage_ids = [r["id"] for r in mirage_rewards]
                cosmetic_ids = [r["id"] for r in cosmetic_rewards]
                invite_code_ids = [r["id"] for r in invite_code_rewards]

                with conn.cursor() as cur:
                    if mirage_ids:
                        for reward in mirage_rewards:
                            cur.execute(
                                """
                                UPDATE pending_rewards
                                SET claimed_at = %s, payout_amount = %s, payout_batch_id = %s
                                WHERE id = %s AND claimed_at IS NULL
                                """,
                                (ts, reward_payouts[reward["id"]], payout_id, reward["id"]),
                            )

                    if cosmetic_ids:
                        cur.execute(
                            """
                            UPDATE pending_rewards
                            SET claimed_at = %s
                            WHERE id = ANY(%s) AND claimed_at IS NULL
                            """,
                            (ts, cosmetic_ids),
                        )

                    if invite_code_ids:
                        cur.execute(
                            """
                            UPDATE pending_rewards
                            SET claimed_at = %s
                            WHERE id = ANY(%s) AND claimed_at IS NULL
                            """,
                            (ts, invite_code_ids),
                        )

                conn.commit()
                return result, payout
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = prev_autocommit

    def _get_multiplier(self, owner: str, ts: int) -> float:
        """Calculate reward multiplier based on completed quest count (1x at 0, 5x at 50)."""
        return get_reward_multiplier(owner)

    def void_pending_rewards(self, owner: str) -> int:
        """
        Void (delete) all pending rewards for a user.

        Used by admins when unsuspending with void_pending=true.

        Returns number of rewards voided.
        """
        with connect_backend_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM pending_rewards
                    WHERE LOWER(owner) = LOWER(%s) AND claimed_at IS NULL
                    RETURNING id
                    """,
                    (owner,),
                )
                return cur.rowcount


# Singleton instance
_distributor: Optional[RewardDistributor] = None


def get_distributor() -> RewardDistributor:
    """Get the singleton RewardDistributor instance."""
    global _distributor
    if _distributor is None:
        _distributor = RewardDistributor()
    return _distributor


__all__ = ["RewardDistributor", "get_distributor"]
