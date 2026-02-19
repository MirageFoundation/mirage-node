#!/usr/bin/env python3
"""
Tests for MsgDeleteUser indexer integration.

Covers: protobuf round-trip, soft-delete profile marking, username resolution
exclusion of deleted profiles, post attribution preservation, profile
recreation after deletion, and address-to-username resolution for deleted users.

Requires a running PostgreSQL database (set DATABASE_URL env var) for DB tests.
Run: python tests/test_delete_user.py
"""
from __future__ import annotations

import os
import sys
import time

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.datatypes import MsgDeleteUser


def test_protobuf_round_trip():
    """MsgDeleteUser serializes and deserializes with all fields intact."""
    msg = MsgDeleteUser()
    msg.authority = "mirage1authority"
    msg.envelope_pubkey = b"\x02" * 33
    msg.envelope_block_hash = b"blockhash"
    msg.envelope_difficulty = 16
    msg.envelope_pow = 99
    msg.envelope_timestamp = 1700000000
    msg.envelope_signature = b"signature"
    msg.target = "mirage1target"

    data = msg.SerializeToString()
    msg2 = MsgDeleteUser()
    msg2.ParseFromString(data)

    assert msg2.authority == "mirage1authority"
    assert msg2.envelope_pubkey == b"\x02" * 33
    assert msg2.envelope_block_hash == b"blockhash"
    assert msg2.envelope_difficulty == 16
    assert msg2.envelope_pow == 99
    assert msg2.envelope_timestamp == 1700000000
    assert msg2.envelope_signature == b"signature"
    assert msg2.target == "mirage1target"
    print("  PASS: protobuf round-trip")


def test_protobuf_empty_fields():
    """MsgDeleteUser with minimal fields (only target) round-trips correctly."""
    msg = MsgDeleteUser()
    msg.target = "mirage1minimal"

    data = msg.SerializeToString()
    msg2 = MsgDeleteUser()
    msg2.ParseFromString(data)

    assert msg2.target == "mirage1minimal"
    assert msg2.authority == ""
    assert msg2.envelope_pubkey == b""
    assert msg2.envelope_difficulty == 0
    print("  PASS: protobuf empty fields")


def test_protobuf_field_numbers():
    """Verify field numbers match Go protobuf definition (especially 10 and 100)."""
    msg = MsgDeleteUser()
    msg.envelope_signature = b"sig"
    msg.target = "mirage1addr"

    data = msg.SerializeToString()

    # Field 10 (envelope_signature): wire type 2 (length-delimited) = (10 << 3) | 2 = 0x52
    assert b"\x52" in data, "field 10 tag byte 0x52 not found"
    # Field 100 (target): varint tag = (100 << 3) | 2 = 802 → varint encoding 0xa2 0x06
    assert b"\xa2\x06" in data, "field 100 tag bytes 0xa2 0x06 not found"
    print("  PASS: protobuf field numbers")


def _get_db():
    """Return a DatabaseManager if DATABASE_URL is set, else None."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None, None
    from indexer.database import DatabaseManager

    return DatabaseManager(db_url), db_url


def _cleanup_test_profiles(db_url, owners):
    """Remove test profiles from the database."""
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            ph = ",".join(["%s"] * len(owners))
            cur.execute(f"DELETE FROM profiles WHERE owner IN ({ph})", owners)


def test_database_soft_delete():
    """soft_delete_profile marks profile, resolve excludes it, get_profile still returns it."""
    db, db_url = _get_db()
    if not db:
        print("  SKIP: DATABASE_URL not set")
        return

    test_owner = "mirage1testdeleteuser"
    test_username = "deleteme_test"
    now = int(time.time())

    try:
        db.upsert_profile(test_owner, test_username, 0, now)

        profile = db.get_profile(test_owner)
        assert profile is not None, "profile should exist"
        assert profile[0] == test_username

        resolved = db.resolve_usernames_to_addresses([test_username])
        assert test_username.lower() in resolved, "username should resolve before deletion"

        rows = db.soft_delete_profile(test_owner, now + 1)
        assert rows == 1, f"expected 1 row affected, got {rows}"

        resolved_after = db.resolve_usernames_to_addresses([test_username])
        assert test_username.lower() not in resolved_after, "deleted username should not resolve"

        profile_after = db.get_profile(test_owner)
        assert profile_after is not None, "profile row should still exist (soft-deleted)"
        assert profile_after[0] == test_username, "username preserved on soft-deleted row"

        rows2 = db.soft_delete_profile(test_owner, now + 2)
        assert rows2 == 0, f"second delete should affect 0 rows, got {rows2}"

        print("  PASS: database soft-delete")
    finally:
        _cleanup_test_profiles(db_url, [test_owner])


def test_upsert_clears_deleted_at():
    """upsert_profile resets deleted_at, re-enabling username resolution."""
    db, db_url = _get_db()
    if not db:
        print("  SKIP: DATABASE_URL not set")
        return

    test_owner = "mirage1testupsertclear"
    test_username = "upsertclear_test"
    now = int(time.time())

    try:
        db.upsert_profile(test_owner, test_username, 0, now)
        db.soft_delete_profile(test_owner, now + 1)

        # Username should not resolve while deleted
        resolved = db.resolve_usernames_to_addresses([test_username])
        assert test_username.lower() not in resolved, "deleted username should not resolve"

        # Re-upsert (simulates chain replay or re-registration)
        db.upsert_profile(test_owner, test_username, 0, now + 2)

        # Username should resolve again
        resolved2 = db.resolve_usernames_to_addresses([test_username])
        assert test_username.lower() in resolved2, "re-upserted username should resolve again"

        print("  PASS: upsert clears deleted_at")
    finally:
        _cleanup_test_profiles(db_url, [test_owner])


def test_upsert_full_clears_deleted_at():
    """upsert_profile_full also resets deleted_at on conflict."""
    db, db_url = _get_db()
    if not db:
        print("  SKIP: DATABASE_URL not set")
        return

    test_owner = "mirage1testfullclear"
    test_username = "fullclear_test"
    now = int(time.time())

    try:
        db.upsert_profile(test_owner, test_username, 0, now)
        db.soft_delete_profile(test_owner, now + 1)

        resolved = db.resolve_usernames_to_addresses([test_username])
        assert test_username.lower() not in resolved

        db.upsert_profile_full(
            owner=test_owner,
            username=test_username,
            level=1,
            created_at=now,
            subscription_expiry=0,
            auto_renew=False,
            is_moderator=False,
            biography="back from the dead",
            avatar="",
            banner="",
            updated_at=now + 2,
        )

        resolved2 = db.resolve_usernames_to_addresses([test_username])
        assert test_username.lower() in resolved2, "full upsert should clear deleted_at"

        print("  PASS: upsert_full clears deleted_at")
    finally:
        _cleanup_test_profiles(db_url, [test_owner])


def test_address_to_username_preserves_deleted():
    """Address-to-username lookups still return the username for deleted profiles (post attribution)."""
    db, db_url = _get_db()
    if not db:
        print("  SKIP: DATABASE_URL not set")
        return

    import psycopg

    test_owner = "mirage1testaddrpreserve"
    test_username = "addrpreserve_test"
    now = int(time.time())

    try:
        db.upsert_profile(test_owner, test_username, 0, now)
        db.soft_delete_profile(test_owner, now + 1)

        # Direct query (same as /api/resolve_address uses)
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username FROM profiles WHERE LOWER(owner) = LOWER(%s) LIMIT 1",
                    (test_owner,),
                )
                row = cur.fetchone()
                assert row is not None, "profile row should exist"
                assert row[0] == test_username, "username should still be returned for deleted profile"

        print("  PASS: address-to-username preserves deleted")
    finally:
        _cleanup_test_profiles(db_url, [test_owner])


def test_deleted_user_excluded_from_search():
    """Deleted profiles should not appear in username search queries."""
    db, db_url = _get_db()
    if not db:
        print("  SKIP: DATABASE_URL not set")
        return

    import psycopg

    test_owner = "mirage1testsearchexcl"
    test_username = "searchexcl_test"
    now = int(time.time())

    try:
        db.upsert_profile(test_owner, test_username, 0, now)

        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Simulate /api/search_username query
                cur.execute(
                    "SELECT username FROM profiles WHERE LOWER(username) LIKE %s AND deleted_at IS NULL LIMIT 10",
                    ("searchexcl%",),
                )
                rows_before = cur.fetchall()
                assert any(r[0] == test_username for r in rows_before), "should find profile before deletion"

        db.soft_delete_profile(test_owner, now + 1)

        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT username FROM profiles WHERE LOWER(username) LIKE %s AND deleted_at IS NULL LIMIT 10",
                    ("searchexcl%",),
                )
                rows_after = cur.fetchall()
                assert not any(r[0] == test_username for r in rows_after), "deleted profile should not appear in search"

        print("  PASS: deleted user excluded from search")
    finally:
        _cleanup_test_profiles(db_url, [test_owner])


def test_soft_delete_different_users_independent():
    """Soft-deleting one user does not affect another user's profile."""
    db, db_url = _get_db()
    if not db:
        print("  SKIP: DATABASE_URL not set")
        return

    owner_a = "mirage1testindep_a"
    owner_b = "mirage1testindep_b"
    user_a = "indep_a_test"
    user_b = "indep_b_test"
    now = int(time.time())

    try:
        db.upsert_profile(owner_a, user_a, 0, now)
        db.upsert_profile(owner_b, user_b, 0, now)

        db.soft_delete_profile(owner_a, now + 1)

        resolved = db.resolve_usernames_to_addresses([user_a, user_b])
        assert user_a.lower() not in resolved, "deleted user should not resolve"
        assert user_b.lower() in resolved, "undeleted user should still resolve"

        print("  PASS: soft-delete independent users")
    finally:
        _cleanup_test_profiles(db_url, [owner_a, owner_b])


def test_message_processor_dispatch():
    """MsgDeleteUser is correctly dispatched by the message processor."""
    from unittest.mock import MagicMock, patch
    from indexer.message_processor import MessageProcessor

    mock_db = MagicMock()
    mock_db.soft_delete_profile.return_value = 1
    mock_chain = MagicMock()

    processor = MessageProcessor(
        db_manager=mock_db,
        chain_client=mock_chain,
        log_yaml_fn=MagicMock(),
        iso_timestamp_fn=lambda ts: "2025-01-01T00:00:00Z",
    )

    msg = MsgDeleteUser()
    msg.target = "mirage1victim"
    value = msg.SerializeToString()
    ts = 1700000000

    processor.process_core_message(
        type_url="/mirage.core.v1.MsgDeleteUser",
        value=value,
        tx_hash="AABBCC",
        ts=ts,
        height=100,
    )

    mock_db.soft_delete_profile.assert_called_once_with("mirage1victim", ts)
    print("  PASS: message processor dispatch")


def test_message_processor_missing_target():
    """MsgDeleteUser with empty target should be rejected gracefully."""
    from unittest.mock import MagicMock
    from indexer.message_processor import MessageProcessor

    mock_db = MagicMock()
    mock_chain = MagicMock()

    processor = MessageProcessor(
        db_manager=mock_db,
        chain_client=mock_chain,
        log_yaml_fn=MagicMock(),
        iso_timestamp_fn=lambda ts: "",
    )

    msg = MsgDeleteUser()
    # target intentionally left empty
    value = msg.SerializeToString()

    processor.process_core_message(
        type_url="/mirage.core.v1.MsgDeleteUser",
        value=value,
        tx_hash="DDEEFF",
        ts=1700000000,
        height=100,
    )

    mock_db.soft_delete_profile.assert_not_called()
    print("  PASS: message processor rejects empty target")


def test_type_url_to_proto_includes_delete_user():
    """MsgDeleteUser is registered in TYPE_URL_TO_PROTO for governance proposal decoding."""
    from indexer.message_processor import TYPE_URL_TO_PROTO

    assert (
        "/mirage.core.v1.MsgDeleteUser" in TYPE_URL_TO_PROTO
    ), "MsgDeleteUser must be in TYPE_URL_TO_PROTO for governance proposal parsing"
    print("  PASS: TYPE_URL_TO_PROTO includes MsgDeleteUser")


def main():
    print("MsgDeleteUser tests:")
    test_protobuf_round_trip()
    test_protobuf_empty_fields()
    test_protobuf_field_numbers()
    test_database_soft_delete()
    test_upsert_clears_deleted_at()
    test_upsert_full_clears_deleted_at()
    test_address_to_username_preserves_deleted()
    test_deleted_user_excluded_from_search()
    test_soft_delete_different_users_independent()
    test_message_processor_dispatch()
    test_message_processor_missing_target()
    test_type_url_to_proto_includes_delete_user()
    print("All tests passed.")


if __name__ == "__main__":
    main()
