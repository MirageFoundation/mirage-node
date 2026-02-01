#!/usr/bin/env python3
"""
Investigate token history for a user.
Run inside Docker container: docker exec -it mirage python /opt/mirage/scripts/investigate_user_tokens.py <username>
"""

import sys
import os

# Add paths for imports
sys.path.insert(0, "/opt/mirage/indexer")
sys.path.insert(0, "/opt/mirage/shared")
sys.path.insert(0, "/opt/mirage/web/backend")

import psycopg


def main():
    if len(sys.argv) < 2:
        print("Usage: investigate_user_tokens.py <username>")
        sys.exit(1)

    username = sys.argv[1]
    db_url = os.environ.get("INDEXER_DB_URL")
    if not db_url:
        print("Error: INDEXER_DB_URL not set")
        sys.exit(1)

    conn = psycopg.connect(db_url, autocommit=True)
    cur = conn.cursor()

    # Find user by username
    print(f"\n=== Looking up user: {username} ===\n")
    cur.execute(
        """
        SELECT owner, username, level, created_at, subscription_expiry, auto_renew
        FROM profiles 
        WHERE LOWER(username) = LOWER(%s)
    """,
        (username,),
    )
    row = cur.fetchone()

    if not row:
        print(f"User '{username}' not found in profiles table")
        sys.exit(1)

    owner, uname, level, created_at, sub_expiry, auto_renew = row
    print(f"Found user:")
    print(f"  Address: {owner}")
    print(f"  Username: {uname}")
    print(f"  Level: {level}")
    print(f"  Created: {created_at}")
    print(f"  Subscription Expiry: {sub_expiry}")
    print(f"  Auto Renew: {auto_renew}")

    # Check referral rewards
    print(f"\n=== Referral Pending Rewards ===\n")
    cur.execute(
        """
        SELECT period_start, period_end, self_active_days, self_reward, referral_reward, 
               total_pending, status, admin_notes, created_at, approved_at, paid_at, paid_txhash
        FROM referral_pending_rewards 
        WHERE LOWER(user_address) = LOWER(%s)
        ORDER BY created_at DESC
    """,
        (owner,),
    )
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  Period: {r[0]} - {r[1]}")
            print(f"    Active days: {r[2]}, Self reward: {r[3]}, Referral reward: {r[4]}")
            print(f"    Total pending: {r[5]}, Status: {r[6]}")
            print(f"    Admin notes: {r[7]}")
            print(f"    Created: {r[8]}, Approved: {r[9]}, Paid: {r[10]}")
            print(f"    Paid txhash: {r[11]}")
            print()
    else:
        print("  No referral pending rewards found")

    # Check referral accruals (as beneficiary)
    print(f"\n=== Referral User Accruals (as beneficiary) ===\n")
    cur.execute(
        """
        SELECT referee_address, level, pending, paid, denied, last_updated
        FROM referral_user_accruals 
        WHERE LOWER(beneficiary_address) = LOWER(%s)
        ORDER BY last_updated DESC
    """,
        (owner,),
    )
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  Referee: {r[0]}")
            print(f"    Level: {r[1]}, Pending: {r[2]}, Paid: {r[3]}, Denied: {r[4]}")
            print(f"    Last updated: {r[5]}")
            print()
    else:
        print("  No referral accruals as beneficiary")

    # Check if this user was referred by someone
    print(f"\n=== Referral Link (who referred this user) ===\n")
    cur.execute(
        """
        SELECT referrer_address, referred_at, created_at
        FROM referral_links 
        WHERE LOWER(user_address) = LOWER(%s)
    """,
        (owner,),
    )
    row = cur.fetchone()
    if row:
        print(f"  Referred by: {row[0]}")
        print(f"  Referred at: {row[1]}, Created: {row[2]}")
    else:
        print("  User was not referred by anyone")

    # Check bridge transactions (inbound/outbound)
    print(f"\n=== Bridge Transactions ===\n")
    cur.execute(
        """
        SELECT tx_hash, direction, msg_type, source_chain, destination_chain, 
               burn_id, sender, recipient, amount, validator, destination_tx,
               minted, created_at, height
        FROM bridge_transactions 
        WHERE LOWER(sender) = LOWER(%s) OR LOWER(recipient) = LOWER(%s)
        ORDER BY created_at DESC
        LIMIT 20
    """,
        (owner, owner),
    )
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  TX: {r[0][:20]}... | Direction: {r[1]} | Type: {r[2]}")
            print(f"    Source: {r[3]} -> Dest: {r[4]}")
            print(f"    Sender: {r[6]}, Recipient: {r[7]}")
            print(f"    Amount: {r[8]} umirage ({r[8]/1_000_000:.2f} MIRAGE)")
            print(f"    Minted: {r[11]}, Created: {r[12]}, Height: {r[13]}")
            print()
    else:
        print("  No bridge transactions found")

    # Check recent posts (paid posts cost tokens)
    print(f"\n=== Recent Posts (last 20) ===\n")
    cur.execute(
        """
        SELECT txhash, topic, title, target, paid, created_at, deleted
        FROM posts 
        WHERE LOWER(owner) = LOWER(%s)
        ORDER BY created_at DESC
        LIMIT 20
    """,
        (owner,),
    )
    rows = cur.fetchall()
    if rows:
        for r in rows:
            title_preview = (r[2] or "")[:50]
            is_comment = "comment" if r[3] else "post"
            paid_str = "PAID" if r[4] else "free"
            deleted_str = " [DELETED]" if r[6] else ""
            print(f"  [{is_comment}] {r[0][:16]}... | {paid_str}{deleted_str}")
            print(f"    Topic: {r[1]}, Title: {title_preview}")
            print(f"    Created: {r[5]}")
            print()
    else:
        print("  No posts found")

    # Check recent votes (votes cost tokens)
    print(f"\n=== Recent Votes (last 20) ===\n")
    cur.execute(
        """
        SELECT txhash, target, user_vote, user_weight, paid, created_at
        FROM votes 
        WHERE LOWER(owner) = LOWER(%s)
        ORDER BY created_at DESC
        LIMIT 20
    """,
        (owner,),
    )
    rows = cur.fetchall()
    if rows:
        for r in rows:
            paid_str = "PAID" if r[4] else "free"
            vote_dir = "UP" if r[2] > 0 else ("DOWN" if r[2] < 0 else "NEUTRAL")
            print(f"  {r[0][:16]}... | {vote_dir} | {paid_str}")
            print(f"    Target: {r[1][:40]}...")
            print(f"    User vote: {r[2]}, Weight: {r[3]}, Created: {r[5]}")
            print()
    else:
        print("  No votes found")

    # Check subscription changes via profile history (if level changed)
    print(f"\n=== Summary ===\n")

    # Count paid activities
    cur.execute("SELECT COUNT(*) FROM posts WHERE LOWER(owner) = LOWER(%s) AND paid = TRUE", (owner,))
    paid_posts = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM votes WHERE LOWER(owner) = LOWER(%s) AND paid = TRUE", (owner,))
    paid_votes = cur.fetchone()[0]

    print(f"  Total paid posts: {paid_posts}")
    print(f"  Total paid votes: {paid_votes}")
    print(f"  User level: {level} (0=free, 1+=subscriber)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
