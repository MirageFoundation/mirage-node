"""
Reward Distributor

Handles distribution of MIRAGE token rewards from the rewards pool to users.

Configuration (via environment variables):
- QUESTS_REWARDS_POOL_ADDRESS: The address holding reward tokens
- QUESTS_PAYOUTS_ENABLED: Set to "true" to enable actual token transfers (default: false)

When QUESTS_PAYOUTS_ENABLED != "true", rewards are logged but not sent.
This allows testing the full flow without requiring a funded rewards pool.

To set up the rewards pool:
1. Add key from seed phrase:
   miraged keys add rewards_pool --recover --keyring-backend test
2. Get the address:
   miraged keys show rewards_pool --keyring-backend test -a
3. Fund the address (governance proposal or direct transfer)
4. Set QUESTS_REWARDS_POOL_ADDRESS and QUESTS_PAYOUTS_ENABLED=true in environment
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import time
from typing import List, Optional, Tuple

from db import connect_backend_db, connect_db
from quest_multiplier import get_reward_multiplier


def get_balance(address) -> int:
    """Read balance from indexer DB."""
    if not address:
        return 0
    with connect_db(timeout=3.0, busy_timeout_ms=5000) as conn:
        cur = conn.cursor()
        cur.execute("SELECT balance FROM balances WHERE address = LOWER(%s)", (str(address),))
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


from node import min_gas_price_umirage

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


def _generate_unique_invite_codes(owner: str, count: int) -> List[str]:
    """Generate unique invite codes and insert them into the database."""
    codes = []
    now_ts = int(time.time())

    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM invite_codes")
            existing = {row[0] for row in cur.fetchall()}

    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            for _ in range(count):
                for attempt in range(100):
                    code = _generate_invite_code()
                    if code not in existing:
                        break
                else:
                    logger.error("Failed to generate unique invite code after 100 attempts")
                    continue

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


# Configuration from environment
QUESTS_REWARDS_POOL_ADDRESS = os.environ.get("QUESTS_REWARDS_POOL_ADDRESS", "")
QUESTS_PAYOUTS_ENABLED = os.environ.get("QUESTS_PAYOUTS_ENABLED", "").lower() == "true"

# Node configuration
NODE_HOME = os.environ.get("NODE_HOME", os.path.expanduser("~/.mirage/node"))
KEYRING_BACKEND = "test"
REWARDS_POOL_KEY_NAME = "rewards_pool"


def _get_miraged_path() -> str:
    """Get the path to the miraged binary."""
    # Check if it's in PATH first
    try:
        result = subprocess.run(["which", "miraged"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback to expected location
    return "/opt/mirage/blockchain/bin/miraged"


def _send_tokens_via_cli(
    from_key: str,
    to_address: str,
    amount: int,
    node_home: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Send tokens using miraged CLI.

    Returns:
        (success, tx_hash, error_message)
    """
    miraged = _get_miraged_path()
    amount_str = f"{amount}umirage"

    # Get the actual minimum gas price from the node config
    gas_price = int(min_gas_price_umirage())
    logger.debug("reward_distributor: using min gas price %s umirage", gas_price)

    cmd = [
        miraged,
        "tx",
        "bank",
        "send",
        from_key,
        to_address,
        amount_str,
        "--home",
        node_home,
        "--keyring-backend",
        KEYRING_BACKEND,
        "--chain-id",
        "mirage-1",
        "--gas",
        "auto",
        "--gas-adjustment",
        "1.5",
        "--gas-prices",
        f"{gas_price}umirage",
        "--yes",  # Skip confirmation
        "--output",
        "json",
    ]

    logger.info(f"Executing: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        logger.info(f"miraged exit code: {result.returncode}")
        logger.info(f"miraged stdout: {result.stdout[:500] if result.stdout else 'empty'}")
        if result.stderr:
            logger.warning(f"miraged stderr: {result.stderr[:500]}")

        if result.returncode != 0:
            raw_error = result.stderr or result.stdout or "Unknown error"
            # Parse common errors into user-friendly messages
            if "key not found" in raw_error.lower():
                return False, None, "rewards_pool_key_not_configured"
            if "insufficient funds" in raw_error.lower():
                return False, None, "insufficient_pool_balance"
            if "account sequence mismatch" in raw_error.lower():
                return False, None, "sequence_mismatch_retry"
            # Log the full error but return a sanitized version
            logger.error(f"miraged tx failed: {raw_error[:500]}")
            return False, None, "payout_transaction_failed"

        # Parse the JSON output to get tx_hash
        try:
            output = json.loads(result.stdout)
            tx_hash = output.get("txhash")
            code = output.get("code", 0)

            if code != 0:
                raw_log = output.get("raw_log", "Transaction failed")
                return False, tx_hash, raw_log

            return True, tx_hash, None
        except json.JSONDecodeError:
            # If not JSON, try to extract tx hash from output
            if "txhash" in result.stdout.lower():
                # Try to find tx hash in output
                for line in result.stdout.split("\n"):
                    if "txhash" in line.lower():
                        parts = line.split(":")
                        if len(parts) >= 2:
                            return True, parts[1].strip(), None
            return True, None, None  # Assume success if no error code

    except subprocess.TimeoutExpired:
        return False, None, "Transaction timed out"
    except Exception as e:
        return False, None, str(e)


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
            logger.warning("QUESTS_PAYOUTS_ENABLED is true but QUESTS_REWARDS_POOL_ADDRESS is not set")
            self.enabled = False

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

    def send_reward(self, recipient: str, amount: int, reason: str) -> dict:
        """
        Send tokens from the rewards pool to a recipient.

        Args:
            recipient: Recipient address
            amount: Amount in umirage
            reason: Human-readable reason (for logging)

        Returns:
            dict with:
            - success: bool
            - tx_hash: str or None
            - amount: int (actual amount sent)
            - error: str or None
        """
        if amount <= 0:
            return {
                "success": False,
                "tx_hash": None,
                "amount": 0,
                "error": "amount must be positive",
            }

        if not self.enabled:
            # Payouts disabled - log but don't send
            logger.info(
                f"[PAYOUTS DISABLED] Would send {amount} umirage to {recipient} "
                f"from {self.pool_address or 'NO_POOL'} ({reason})"
            )
            return {
                "success": True,
                "tx_hash": None,
                "amount": amount,
                "error": None,
            }

        # Check balance
        pool_balance = self.get_pool_balance()
        if pool_balance < amount:
            logger.warning(f"Insufficient pool balance: have {pool_balance}, need {amount} for {recipient}")
            return {
                "success": False,
                "tx_hash": None,
                "amount": 0,
                "error": "insufficient_pool_balance",
            }

        # Live mode - actually send tokens via miraged CLI
        logger.info(f"[LIVE] Sending {amount} umirage to {recipient} from {self.pool_address} ({reason})")

        success, tx_hash, error = _send_tokens_via_cli(
            from_key=REWARDS_POOL_KEY_NAME,
            to_address=recipient,
            amount=amount,
            node_home=NODE_HOME,
        )

        if not success:
            logger.error(f"Failed to send tokens: {error}")
            return {
                "success": False,
                "tx_hash": tx_hash,
                "amount": 0,
                "error": error or "transaction_failed",
            }

        logger.info(f"[LIVE] Successfully sent {amount} umirage to {recipient}, tx_hash={tx_hash}")

        return {
            "success": True,
            "tx_hash": tx_hash,
            "amount": amount,
            "error": None,
        }

    def claim_rewards(self, owner: str, ts: int) -> dict:
        """
        Process a reward claim for a user.

        This is called from the /api/rewards/claim endpoint.

        Serializes per-owner via pg_advisory_xact_lock so concurrent claims
        cannot both read the same unclaimed rows and double-pay. The lock is
        held across the payout subprocess and the claimed_at UPDATE.

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
                        """,
                        (owner_lc,),
                    )
                    rows = cur.fetchall()

                if not rows:
                    conn.commit()
                    return {
                        "success": False,
                        "rewards": [],
                        "tx_hash": None,
                        "error": "no_rewards",
                    }

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
                        invite_code_rewards.append(
                            {
                                "id": reward_id,
                                "amount": reward_data.get("amount", 1),
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

                result = {
                    "success": True,
                    "rewards": [],
                    "tx_hash": None,
                    "error": None,
                }

                # Process MIRAGE rewards while the advisory lock is held so a
                # concurrent claim waits and then finds nothing unclaimed.
                if mirage_rewards and payout_amount > 0:
                    send_result = self.send_reward(
                        owner_lc, payout_amount, f"quest_rewards:{len(mirage_rewards)}_quests"
                    )

                    if send_result["success"]:
                        result["tx_hash"] = send_result.get("tx_hash")
                        result["rewards"].append(
                            {
                                "type": "mirage",
                                "amount": payout_amount,
                                "raw_amount": total_mirage,
                                "multiplier": round(multiplier, 4),
                            }
                        )
                    else:
                        # Failed to send - don't mark as claimed
                        logger.error(
                            f"Failed to send MIRAGE rewards to {owner_lc}: {send_result.get('error')}"
                        )
                        conn.rollback()
                        result["success"] = False
                        result["error"] = send_result.get("error")
                        return result

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
                    codes = _generate_unique_invite_codes(owner_lc, count)
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
                            if reward.get("apply_multiplier", True):
                                reward_payout = int(reward["amount"] * multiplier)
                            else:
                                reward_payout = reward["amount"]
                            cur.execute(
                                """
                                UPDATE pending_rewards
                                SET claimed_at = %s, payout_amount = %s
                                WHERE id = %s AND claimed_at IS NULL
                                """,
                                (ts, reward_payout, reward["id"]),
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
                return result
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
