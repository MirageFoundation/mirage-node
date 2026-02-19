#!/usr/bin/env python3
"""
Dynamic protobuf message classes for Mirage custom types.

Exports:
- MsgSubmit

These are dynamic classes compatible with CosmPy Aerial Transaction.add_message.
"""
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


def _build_pool():
    pool = descriptor_pool.DescriptorPool()
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "mirage_messages.proto"
    file_proto.package = "mirage.core.v1"
    file_proto.syntax = "proto3"

    # Helper to add message without fields
    def add_msg(name: str):
        msg = file_proto.message_type.add()
        msg.name = name
        return msg

    # QueryParamsRequest (empty)
    add_msg("QueryParamsRequest")

    # MsgPost
    msg = file_proto.message_type.add()
    msg.name = "MsgPost"

    def add_f(m, name, num, ftype, repeated=False):
        f = m.field.add()
        f.name = name
        f.number = num
        f.label = (
            descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
            if repeated
            else descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        )
        f.type = ftype

    add_f(msg, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "topic", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "title", 102, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "content", 103, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "tag", 104, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "media", 105, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)

    # MsgEdit
    msg_edit = file_proto.message_type.add()
    msg_edit.name = "MsgEdit"
    add_f(msg_edit, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_edit, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_edit, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_edit, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_edit, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_edit, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_edit, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "topic", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "title", 102, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "content", 103, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "tag", 104, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "override", 105, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "media", 106, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)

    # MsgVote
    msg2 = file_proto.message_type.add()
    msg2.name = "MsgVote"
    add_f(msg2, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg2, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg2, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg2, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg2, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg2, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg2, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg2, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg2, "direction", 101, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)

    # MsgSetUsername
    msg3 = file_proto.message_type.add()
    msg3.name = "MsgSetUsername"
    add_f(msg3, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg3, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg3, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg3, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg3, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg3, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg3, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg3, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg3, "username", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgFollowModerator
    msg_follow = file_proto.message_type.add()
    msg_follow.name = "MsgFollowModerator"
    add_f(msg_follow, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow, "moderator", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgUnfollowModerator
    msg_unfollow = file_proto.message_type.add()
    msg_unfollow.name = "MsgUnfollowModerator"
    add_f(msg_unfollow, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow, "moderator", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgFollowUser
    msg_follow_user = file_proto.message_type.add()
    msg_follow_user.name = "MsgFollowUser"
    add_f(msg_follow_user, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow_user, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_user, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_user, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_user, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_user, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_user, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_user, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow_user, "user", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgUnfollowUser
    msg_unfollow_user = file_proto.message_type.add()
    msg_unfollow_user.name = "MsgUnfollowUser"
    add_f(msg_unfollow_user, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow_user, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow_user, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow_user, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow_user, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow_user, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow_user, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow_user, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow_user, "user", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgFollowTopic
    msg_follow_topic = file_proto.message_type.add()
    msg_follow_topic.name = "MsgFollowTopic"
    add_f(msg_follow_topic, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow_topic, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_topic, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_topic, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_topic, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_topic, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_topic, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_topic, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow_topic, "topic", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgUnfollowTopic
    msg_unfollow_topic = file_proto.message_type.add()
    msg_unfollow_topic.name = "MsgUnfollowTopic"
    add_f(msg_unfollow_topic, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow_topic, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow_topic, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow_topic, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow_topic, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow_topic, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow_topic, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow_topic, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow_topic, "topic", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgBlockPost
    msg_block_post = file_proto.message_type.add()
    msg_block_post.name = "MsgBlockPost"
    add_f(msg_block_post, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_block_post, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_post, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_post, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_post, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_post, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_post, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_post, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgUnblockPost
    msg_unblock_post = file_proto.message_type.add()
    msg_unblock_post.name = "MsgUnblockPost"
    add_f(msg_unblock_post, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unblock_post, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_post, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_post, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_post, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_post, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_post, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_post, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgBlockUser
    msg_block_user = file_proto.message_type.add()
    msg_block_user.name = "MsgBlockUser"
    add_f(msg_block_user, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_block_user, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_user, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_user, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_user, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_user, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_user, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_user, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgUnblockUser
    msg_unblock_user = file_proto.message_type.add()
    msg_unblock_user.name = "MsgUnblockUser"
    add_f(msg_unblock_user, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unblock_user, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_user, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_user, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_user, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_user, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_user, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_user, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgBlockTopic
    msg_block_topic = file_proto.message_type.add()
    msg_block_topic.name = "MsgBlockTopic"
    add_f(msg_block_topic, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_block_topic, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_topic, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_topic, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_topic, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_topic, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_block_topic, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_block_topic, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_block_topic, "topic", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgUnblockTopic
    msg_unblock_topic = file_proto.message_type.add()
    msg_unblock_topic.name = "MsgUnblockTopic"
    add_f(msg_unblock_topic, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unblock_topic, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_topic, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_topic, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_topic, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_topic, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unblock_topic, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unblock_topic, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unblock_topic, "topic", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgDelete
    msg_delete = file_proto.message_type.add()
    msg_delete.name = "MsgDelete"
    add_f(msg_delete, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_delete, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_delete, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_delete, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_delete, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_delete, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_delete, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_delete, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgDeleteUser (permanently removes a user account)
    msg_delete_user = file_proto.message_type.add()
    msg_delete_user.name = "MsgDeleteUser"
    add_f(msg_delete_user, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_delete_user, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_delete_user, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_delete_user, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_delete_user, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_delete_user, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_delete_user, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_delete_user, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgSendTokens
    msg_send_tokens = file_proto.message_type.add()
    msg_send_tokens.name = "MsgSendTokens"
    add_f(msg_send_tokens, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_send_tokens, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_send_tokens, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_send_tokens, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_send_tokens, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_send_tokens, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_send_tokens, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_send_tokens, "sender", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_send_tokens, "target", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_send_tokens, "amount", 102, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # MsgSetLevel (governance only)
    msg_set_level = file_proto.message_type.add()
    msg_set_level.name = "MsgSetLevel"
    add_f(msg_set_level, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_set_level, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_level, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_level, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_level, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_level, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_level, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_level, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_set_level, "level", 101, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)

    # MsgMintTokens (governance only)
    msg_mint_tokens = file_proto.message_type.add()
    msg_mint_tokens.name = "MsgMintTokens"
    add_f(msg_mint_tokens, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_mint_tokens, "target", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_mint_tokens, "amount", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_mint_tokens, "reason", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgMintTokensResponse
    msg_mint_tokens_resp = file_proto.message_type.add()
    msg_mint_tokens_resp.name = "MsgMintTokensResponse"

    # MsgBurnTokens (governance only)
    msg_burn_tokens = file_proto.message_type.add()
    msg_burn_tokens.name = "MsgBurnTokens"
    add_f(msg_burn_tokens, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_burn_tokens, "target", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_burn_tokens, "amount", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_burn_tokens, "reason", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgBurnTokensResponse
    msg_burn_tokens_resp = file_proto.message_type.add()
    msg_burn_tokens_resp.name = "MsgBurnTokensResponse"

    # MsgUpgradeLevel (user-initiated tier upgrade)
    msg_upgrade_level = file_proto.message_type.add()
    msg_upgrade_level.name = "MsgUpgradeLevel"
    add_f(msg_upgrade_level, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_upgrade_level, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_upgrade_level, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_upgrade_level, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_upgrade_level, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_upgrade_level, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_upgrade_level, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_upgrade_level, "level", 100, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)

    # MsgSetAutoRenewal (user-initiated toggle of auto_renew)
    msg_set_auto = file_proto.message_type.add()
    msg_set_auto.name = "MsgSetAutoRenewal"
    add_f(msg_set_auto, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_set_auto, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_auto, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_auto, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_auto, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_auto, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_auto, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_auto, "auto_renew", 100, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    # MsgBridgeBurn (burn MIRAGE for bridging to non-IBC chains like Solana)
    msg_bridge_burn = file_proto.message_type.add()
    msg_bridge_burn.name = "MsgBridgeBurn"
    add_f(msg_bridge_burn, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_bridge_burn, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_bridge_burn, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bridge_burn, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bridge_burn, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bridge_burn, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_bridge_burn, "destination_chain", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn, "destination_address", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn, "amount", 102, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # TierConfig (tier configuration for subscription levels)
    tier_config = file_proto.message_type.add()
    tier_config.name = "TierConfig"
    add_f(tier_config, "period_fee", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_followed_mods", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_followed_users", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_followed_topics", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_blocked_users", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_blocked_posts", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_blocked_topics", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_title_length", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_content_length", 9, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "editing_time_mins", 10, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "archive_duration_days", 12, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "vote_weight", 13, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(tier_config, "award_permissions", 14, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
    add_f(tier_config, "eligible_for_mod", 15, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "can_change_name", 16, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "can_have_biography", 17, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "can_have_avatar", 18, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "can_have_banner", 19, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    # BridgeChainConfig (used in Params.bridge_chains)
    bridge_config = file_proto.message_type.add()
    bridge_config.name = "BridgeChainConfig"
    add_f(bridge_config, "chain_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(bridge_config, "enabled", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(bridge_config, "fee", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # MsgBridgeAttestBurned (validator attestation for external chain burns - inbound)
    msg_bridge_attest_burned = file_proto.message_type.add()
    msg_bridge_attest_burned.name = "MsgBridgeAttestBurned"
    add_f(msg_bridge_attest_burned, "validator", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_burned, "source_chain", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_burned, "burn_id", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_burned, "mirage_recipient", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_burned, "amount", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # MsgBridgeAttestBurnedResponse
    msg_bridge_attest_burned_resp = file_proto.message_type.add()
    msg_bridge_attest_burned_resp.name = "MsgBridgeAttestBurnedResponse"
    add_f(msg_bridge_attest_burned_resp, "confirmed", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(msg_bridge_attest_burned_resp, "attested_power", 2, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_bridge_attest_burned_resp, "required_power", 3, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)

    # MsgBridgeAttestMinted (validator attestation for external chain mints - outbound)
    msg_bridge_attest_minted = file_proto.message_type.add()
    msg_bridge_attest_minted.name = "MsgBridgeAttestMinted"
    add_f(msg_bridge_attest_minted, "validator", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_minted, "burn_id", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_minted, "destination_chain", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_minted, "destination_tx", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_minted, "mirage_tx_hash", 5, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgBridgeAttestMintedResponse
    msg_bridge_attest_minted_resp = file_proto.message_type.add()
    msg_bridge_attest_minted_resp.name = "MsgBridgeAttestMintedResponse"
    add_f(msg_bridge_attest_minted_resp, "confirmed", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(msg_bridge_attest_minted_resp, "attested_power", 2, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_bridge_attest_minted_resp, "required_power", 3, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)

    # Params (module parameters) - ALL fields from proto/mirage/core/v1/params.proto
    msg4 = file_proto.message_type.add()
    msg4.name = "Params"
    add_f(msg4, "pow_base_bits", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_message_window", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_increase_threshold", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_calm_period_definition", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_calm_sequence_threshold", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_interval", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_quantity", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "block_hash_window", 9, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_difficulty_grace_period", 10, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_username_size", 34, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_topic_size", 35, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "min_username_size", 36, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "min_topic_size", 37, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_dynamic_credit_cap", 38, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_dynamic_fraction", 39, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(msg4, "subscription_period", 40, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    # tiers is a repeated TierConfig (field 41)
    f_tiers = msg4.field.add()
    f_tiers.name = "tiers"
    f_tiers.number = 41
    f_tiers.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_tiers.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f_tiers.type_name = ".mirage.core.v1.TierConfig"
    add_f(msg4, "subscription_reserve_fraction", 42, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(msg4, "relay_min_gas_price", 43, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "relay_max_gas_fee", 44, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_envelope_age", 45, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    # bridge_chains is a repeated BridgeChainConfig (field 50)
    f_bridge = msg4.field.add()
    f_bridge.name = "bridge_chains"
    f_bridge.number = 50
    f_bridge.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_bridge.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f_bridge.type_name = ".mirage.core.v1.BridgeChainConfig"
    add_f(msg4, "bridge_attestation_threshold", 51, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(msg4, "pow_factor", 52, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)

    # MsgUpdateParams (authority + Params)
    msg5 = file_proto.message_type.add()
    msg5.name = "MsgUpdateParams"
    add_f(msg5, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    f = msg5.field.add()
    f.name = "params"
    f.number = 2
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f.type_name = ".mirage.core.v1.Params"

    # QueryParamsResponse (wraps Params)
    msg6 = file_proto.message_type.add()
    msg6.name = "QueryParamsResponse"
    f = msg6.field.add()
    f.name = "params"
    f.number = 1
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f.type_name = ".mirage.core.v1.Params"

    # QueryDifficultyRequest (empty)
    add_msg("QueryDifficultyRequest")

    # QueryDifficultyResponse
    msg_diff = file_proto.message_type.add()
    msg_diff.name = "QueryDifficultyResponse"
    add_f(msg_diff, "current_difficulty", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_diff, "previous_difficulty", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_diff, "last_change_height", 3, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_diff, "pow_message_count", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_diff, "consecutive_low_usage", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_diff, "latest_block_hash", 6, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_diff, "current_height", 7, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_diff, "pow_base_bits", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # BridgeChainStatus
    msg_bridge_chain_status = file_proto.message_type.add()
    msg_bridge_chain_status.name = "BridgeChainStatus"
    add_f(msg_bridge_chain_status, "chain_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_chain_status, "current_sequence", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # QueryBridgeStatusRequest (empty)
    add_msg("QueryBridgeStatusRequest")

    # QueryBridgeStatusResponse
    msg_bridge_status_resp = file_proto.message_type.add()
    msg_bridge_status_resp.name = "QueryBridgeStatusResponse"
    f_enabled = msg_bridge_status_resp.field.add()
    f_enabled.name = "enabled_chains"
    f_enabled.number = 1
    f_enabled.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_enabled.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f_enabled.type_name = ".mirage.core.v1.BridgeChainConfig"
    add_f(msg_bridge_status_resp, "pending_attestations_count", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    f_chain_status = msg_bridge_status_resp.field.add()
    f_chain_status.name = "chain_status"
    f_chain_status.number = 3
    f_chain_status.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_chain_status.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f_chain_status.type_name = ".mirage.core.v1.BridgeChainStatus"

    # QueryBridgeMintRequest
    msg_bridge_mint_req = file_proto.message_type.add()
    msg_bridge_mint_req.name = "QueryBridgeMintRequest"
    add_f(msg_bridge_mint_req, "destination_chain", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_mint_req, "burn_id", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # QueryBridgeMintResponse
    msg_bridge_mint_resp = file_proto.message_type.add()
    msg_bridge_mint_resp.name = "QueryBridgeMintResponse"
    add_f(msg_bridge_mint_resp, "minted", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(msg_bridge_mint_resp, "destination_chain", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_mint_resp, "destination_tx", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_mint_resp, "found", 4, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    # attestors is repeated string (field 5)
    f_attestors_mint = msg_bridge_mint_resp.field.add()
    f_attestors_mint.name = "attestors"
    f_attestors_mint.number = 5
    f_attestors_mint.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_attestors_mint.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    add_f(msg_bridge_mint_resp, "attested_power", 6, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_bridge_mint_resp, "required_power", 7, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)

    # QueryBridgeAttestationRequest (for inbound bridges)
    msg_bridge_attest_req = file_proto.message_type.add()
    msg_bridge_attest_req.name = "QueryBridgeAttestationRequest"
    add_f(msg_bridge_attest_req, "source_chain", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_req, "burn_id", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # QueryBridgeAttestationResponse
    msg_bridge_attest_resp = file_proto.message_type.add()
    msg_bridge_attest_resp.name = "QueryBridgeAttestationResponse"
    add_f(msg_bridge_attest_resp, "found", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(msg_bridge_attest_resp, "source_chain", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_resp, "burn_id", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_resp, "mirage_recipient", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_attest_resp, "amount", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    # Note: attestors is repeated string but we'll skip for simplicity
    add_f(msg_bridge_attest_resp, "attested_power", 7, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_bridge_attest_resp, "required_power", 8, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_bridge_attest_resp, "minted", 9, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(msg_bridge_attest_resp, "created_at", 10, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)

    # QueryBridgeBurnRequest
    msg_bridge_burn_req = file_proto.message_type.add()
    msg_bridge_burn_req.name = "QueryBridgeBurnRequest"
    add_f(msg_bridge_burn_req, "destination_chain", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn_req, "burn_id", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # QueryBridgeBurnResponse
    msg_bridge_burn_resp = file_proto.message_type.add()
    msg_bridge_burn_resp.name = "QueryBridgeBurnResponse"
    add_f(msg_bridge_burn_resp, "found", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(msg_bridge_burn_resp, "burn_id", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn_resp, "owner", 3, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn_resp, "destination_chain", 4, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn_resp, "destination_address", 5, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bridge_burn_resp, "amount", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bridge_burn_resp, "bridge_fee", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bridge_burn_resp, "sequence", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bridge_burn_resp, "created_at", 9, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)

    pool.Add(file_proto)
    return pool


_POOL = _build_pool()


def _get_message_class(full_name: str):
    try:
        from google.protobuf.message_factory import GetMessageClass  # type: ignore

        desc = _POOL.FindMessageTypeByName(full_name)
        return GetMessageClass(desc)
    except Exception:
        factory = message_factory.MessageFactory(_POOL)
        desc = _POOL.FindMessageTypeByName(full_name)
        return factory.GetPrototype(desc)


# Export classes
MsgPost = _get_message_class("mirage.core.v1.MsgPost")
MsgEdit = _get_message_class("mirage.core.v1.MsgEdit")
MsgVote = _get_message_class("mirage.core.v1.MsgVote")
MsgSetUsername = _get_message_class("mirage.core.v1.MsgSetUsername")
MsgFollowModerator = _get_message_class("mirage.core.v1.MsgFollowModerator")
MsgUnfollowModerator = _get_message_class("mirage.core.v1.MsgUnfollowModerator")
MsgFollowUser = _get_message_class("mirage.core.v1.MsgFollowUser")
MsgUnfollowUser = _get_message_class("mirage.core.v1.MsgUnfollowUser")
MsgFollowTopic = _get_message_class("mirage.core.v1.MsgFollowTopic")
MsgUnfollowTopic = _get_message_class("mirage.core.v1.MsgUnfollowTopic")
MsgBlockPost = _get_message_class("mirage.core.v1.MsgBlockPost")
MsgUnblockPost = _get_message_class("mirage.core.v1.MsgUnblockPost")
MsgBlockUser = _get_message_class("mirage.core.v1.MsgBlockUser")
MsgUnblockUser = _get_message_class("mirage.core.v1.MsgUnblockUser")
MsgBlockTopic = _get_message_class("mirage.core.v1.MsgBlockTopic")
MsgUnblockTopic = _get_message_class("mirage.core.v1.MsgUnblockTopic")
MsgDelete = _get_message_class("mirage.core.v1.MsgDelete")
MsgDeleteUser = _get_message_class("mirage.core.v1.MsgDeleteUser")
MsgSendTokens = _get_message_class("mirage.core.v1.MsgSendTokens")
MsgSetLevel = _get_message_class("mirage.core.v1.MsgSetLevel")
MsgMintTokens = _get_message_class("mirage.core.v1.MsgMintTokens")
MsgMintTokensResponse = _get_message_class("mirage.core.v1.MsgMintTokensResponse")
MsgBurnTokens = _get_message_class("mirage.core.v1.MsgBurnTokens")
MsgBurnTokensResponse = _get_message_class("mirage.core.v1.MsgBurnTokensResponse")
MsgUpgradeLevel = _get_message_class("mirage.core.v1.MsgUpgradeLevel")
MsgSetAutoRenewal = _get_message_class("mirage.core.v1.MsgSetAutoRenewal")
MsgBridgeBurn = _get_message_class("mirage.core.v1.MsgBridgeBurn")
MsgBridgeAttestBurned = _get_message_class("mirage.core.v1.MsgBridgeAttestBurned")
MsgBridgeAttestBurnedResponse = _get_message_class("mirage.core.v1.MsgBridgeAttestBurnedResponse")
MsgBridgeAttestMinted = _get_message_class("mirage.core.v1.MsgBridgeAttestMinted")
MsgBridgeAttestMintedResponse = _get_message_class("mirage.core.v1.MsgBridgeAttestMintedResponse")
TierConfig = _get_message_class("mirage.core.v1.TierConfig")
BridgeChainConfig = _get_message_class("mirage.core.v1.BridgeChainConfig")
Params = _get_message_class("mirage.core.v1.Params")
MsgUpdateParams = _get_message_class("mirage.core.v1.MsgUpdateParams")
QueryParamsRequest = _get_message_class("mirage.core.v1.QueryParamsRequest")
QueryParamsResponse = _get_message_class("mirage.core.v1.QueryParamsResponse")
QueryDifficultyRequest = _get_message_class("mirage.core.v1.QueryDifficultyRequest")
QueryDifficultyResponse = _get_message_class("mirage.core.v1.QueryDifficultyResponse")
BridgeChainStatus = _get_message_class("mirage.core.v1.BridgeChainStatus")
QueryBridgeStatusRequest = _get_message_class("mirage.core.v1.QueryBridgeStatusRequest")
QueryBridgeStatusResponse = _get_message_class("mirage.core.v1.QueryBridgeStatusResponse")
QueryBridgeMintRequest = _get_message_class("mirage.core.v1.QueryBridgeMintRequest")
QueryBridgeMintResponse = _get_message_class("mirage.core.v1.QueryBridgeMintResponse")
QueryBridgeAttestationRequest = _get_message_class("mirage.core.v1.QueryBridgeAttestationRequest")
QueryBridgeAttestationResponse = _get_message_class("mirage.core.v1.QueryBridgeAttestationResponse")
QueryBridgeBurnRequest = _get_message_class("mirage.core.v1.QueryBridgeBurnRequest")
QueryBridgeBurnResponse = _get_message_class("mirage.core.v1.QueryBridgeBurnResponse")
