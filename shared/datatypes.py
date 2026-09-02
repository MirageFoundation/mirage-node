#!/usr/bin/env python3
"""
Dynamic protobuf message classes for Mirage custom types.

Exports:
- MsgSubmit

These are dynamic classes compatible with CosmPy Aerial Transaction.add_message.
"""
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf import field_mask_pb2


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
    add_f(msg, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "community", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "title", 102, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "content", 103, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "tag", 104, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg, "media", 105, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)
    add_f(msg, "protocol_version", 106, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)

    # MsgEdit
    msg_edit = file_proto.message_type.add()
    msg_edit.name = "MsgEdit"
    add_f(msg_edit, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_edit, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_edit, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_edit, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_edit, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_edit, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_edit, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_edit, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "community", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "title", 102, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "content", 103, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "tag", 104, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "override", 105, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_edit, "media", 106, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)

    # MsgAnnotate (agent overlay on existing post)
    msg_annotate = file_proto.message_type.add()
    msg_annotate.name = "MsgAnnotate"
    add_f(msg_annotate, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_annotate, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_annotate, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_annotate, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_annotate, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_annotate, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_annotate, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_annotate, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_annotate, "topic", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_annotate, "title", 102, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_annotate, "content", 103, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_annotate, "tag", 104, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_annotate, "override", 105, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_annotate, "media", 106, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)
    add_f(msg_annotate, "appendix", 107, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgVote
    msg2 = file_proto.message_type.add()
    msg2.name = "MsgVote"
    add_f(msg2, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg2, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg2, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg2, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg2, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg2, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg2, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg3, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg3, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg3, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg3, "username", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgSetBiography
    msg_bio = file_proto.message_type.add()
    msg_bio.name = "MsgSetBiography"
    add_f(msg_bio, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bio, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_bio, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_bio, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bio, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bio, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bio, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_bio, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_bio, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_bio, "biography", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgEnableAgent
    msg_follow = file_proto.message_type.add()
    msg_follow.name = "MsgEnableAgent"
    add_f(msg_follow, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow, "agent", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgDisableAgent
    msg_unfollow = file_proto.message_type.add()
    msg_unfollow.name = "MsgDisableAgent"
    add_f(msg_unfollow, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_unfollow, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_unfollow, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_unfollow, "agent", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgSetAgents
    msg_set_agents = file_proto.message_type.add()
    msg_set_agents.name = "MsgSetAgents"
    add_f(msg_set_agents, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_set_agents, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_agents, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_agents, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_agents, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_agents, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_agents, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_agents, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_agents, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_set_agents, "agents", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)

    # MsgFollowUser
    msg_follow_user = file_proto.message_type.add()
    msg_follow_user.name = "MsgFollowUser"
    add_f(msg_follow_user, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_follow_user, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_user, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_follow_user, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_user, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_user, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_follow_user, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_unfollow_user, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_follow_topic, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_unfollow_topic, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_block_post, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_unblock_post, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_block_user, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_unblock_user, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_block_topic, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_unblock_topic, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_delete, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_delete_user, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_send_tokens, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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
    add_f(msg_set_level, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
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

    # MsgSubscribe (subscribe to paid tier — self or gift)
    msg_subscribe = file_proto.message_type.add()
    msg_subscribe.name = "MsgSubscribe"
    add_f(msg_subscribe, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_subscribe, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_subscribe, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_subscribe, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_subscribe, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_subscribe, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_subscribe, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_subscribe, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_subscribe, "level", 100, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)
    add_f(msg_subscribe, "target", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_subscribe, "period_count", 102, descriptor_pb2.FieldDescriptorProto.TYPE_UINT32)

    # MsgSetAutoRenewal (user-initiated toggle of auto_renew)
    msg_set_auto = file_proto.message_type.add()
    msg_set_auto.name = "MsgSetAutoRenewal"
    add_f(msg_set_auto, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_set_auto, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_auto, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_auto, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_auto, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_auto, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_auto, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_set_auto, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_set_auto, "auto_renew", 100, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    # TierConfig (tier configuration for subscription levels)
    tier_config = file_proto.message_type.add()
    tier_config.name = "TierConfig"
    add_f(tier_config, "period_fee", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_followed_users", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_joined_communities", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_blocked_users", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_blocked_posts", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_blocked_communities", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_title_length", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_content_length", 9, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "editing_time_mins", 10, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "vote_weight", 13, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(tier_config, "can_have_biography", 17, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "can_have_avatar", 18, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "can_have_banner", 19, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "can_have_flair", 20, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(tier_config, "max_biography_length", 21, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_curation_memberships", 22, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(tier_config, "max_daily_relays", 23, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # AwardConfig (used in Params.award_configs)
    award_config = file_proto.message_type.add()
    award_config.name = "AwardConfig"
    add_f(award_config, "name", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(award_config, "cost", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # MsgAward (give an award to a post/comment, burning MIRAGE)
    msg_award = file_proto.message_type.add()
    msg_award.name = "MsgAward"
    add_f(msg_award, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_award, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_award, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_award, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_award, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_award, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_award, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_award, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(msg_award, "target", 100, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_award, "award_type", 101, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # MsgAwardResponse
    msg_award_resp = file_proto.message_type.add()
    msg_award_resp.name = "MsgAwardResponse"

    # Params (module parameters) - ALL fields from proto/mirage/core/v1/params.proto
    #
    # Field NAMES here MUST match the chain proto exactly so that
    # google.protobuf.json_format.ParseDict() can decode REST-formatted
    # governance MsgUpdateParams payloads (which use the chain's proto names).
    # Legacy aliases (pow_base_bits, pow_increase_threshold,
    # pow_difficulty_grace_period, pow_factor) are re-added downstream in
    # indexer/params.py::_query_core_params so existing backend/frontend/agent
    # consumers keep working unchanged. QueryDifficultyResponse tag 8 is also
    # aligned here to min_difficulty (was pow_base_bits in old Python schema).
    msg4 = file_proto.message_type.add()
    msg4.name = "Params"
    add_f(msg4, "min_difficulty", 1, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_message_window", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_message_limit", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_calm_period_definition", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_calm_sequence_threshold", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_interval", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_quantity", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "block_hash_window", 9, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_difficulty_allowance", 10, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_username_size", 34, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_community_size", 35, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "min_username_size", 36, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "min_community_size", 37, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_dynamic_credit_cap", 38, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_dynamic_split", 39, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(msg4, "subscription_period", 40, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    # tiers is a repeated TierConfig (field 41)
    f_tiers = msg4.field.add()
    f_tiers.name = "tiers"
    f_tiers.number = 41
    f_tiers.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_tiers.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f_tiers.type_name = ".mirage.core.v1.TierConfig"
    # Superseded by subscription_reserve_bps (field 54) and always 0 from v1.34.0.
    # Kept so params blobs written before the upgrade still decode.
    add_f(msg4, "subscription_reserve_percent", 42, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(msg4, "relay_min_gas_price", 43, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "relay_max_gas_fee", 44, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_envelope_age", 45, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "pow_difficulty_step", 52, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    # award_configs is a repeated AwardConfig (field 53)
    f_awards = msg4.field.add()
    f_awards.name = "award_configs"
    f_awards.number = 53
    f_awards.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f_awards.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f_awards.type_name = ".mirage.core.v1.AwardConfig"
    add_f(msg4, "subscription_reserve_bps", 54, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "mint_floor_split", 55, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    add_f(msg4, "subscription_creator_bps", 56, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_curators_per_team", 57, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_pending_curator_invites_per_team", 58, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_pending_curator_invites_per_user", 59, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_curation_team_name_length", 62, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_curation_team_description_length", 63, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "subscription_transitions_per_block", 65, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "curation_prune_keys_per_block", 66, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "creator_epoch_closures_per_block", 67, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "creator_settlement_records_per_block", 68, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "creator_prune_keys_per_block", 69, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "creator_claim_window_days", 70, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_creator_claim_epochs", 71, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_creator_engagements_per_epoch", 72, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "creator_epoch_expiries_per_block", 73, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "subscription_early_renewal_days", 74, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "subscription_renewal_attempts_per_block", 75, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "subscriber_daily_relay_limit", 76, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "max_subscription_periods_per_purchase", 77, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg4, "creator_epoch_seconds", 78, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # MsgUpdateParams (authority + Params + update_mask)
    #
    # update_mask (field 3) selects which Params fields a governance proposal
    # applies. Without it in this schema, a decoded MsgUpdateParams would drop
    # the mask and the indexer could not tell which fields a proposal changed.
    # The well-known FieldMask descriptor is registered in this pool because the
    # pool is built from scratch and does not inherit the default one.
    pool.Add(descriptor_pb2.FileDescriptorProto.FromString(field_mask_pb2.DESCRIPTOR.serialized_pb))
    file_proto.dependency.append("google/protobuf/field_mask.proto")

    msg5 = file_proto.message_type.add()
    msg5.name = "MsgUpdateParams"
    add_f(msg5, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    f = msg5.field.add()
    f.name = "params"
    f.number = 2
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f.type_name = ".mirage.core.v1.Params"
    f = msg5.field.add()
    f.name = "update_mask"
    f.number = 3
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f.type_name = ".google.protobuf.FieldMask"

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
    add_f(msg_diff, "min_difficulty", 8, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    # QueryProfileRequest
    msg_profile_req = file_proto.message_type.add()
    msg_profile_req.name = "QueryProfileRequest"
    add_f(msg_profile_req, "address", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    # QueryProfileResponse
    msg_profile_resp = file_proto.message_type.add()
    msg_profile_resp.name = "QueryProfileResponse"
    add_f(msg_profile_resp, "owner", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_profile_resp, "username", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_profile_resp, "level", 3, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    add_f(msg_profile_resp, "created_at", 4, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_profile_resp, "subscription_expiry", 5, descriptor_pb2.FieldDescriptorProto.TYPE_INT64)
    add_f(msg_profile_resp, "auto_renew", 6, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(msg_profile_resp, "reserve_funds", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(msg_profile_resp, "biography", 9, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_profile_resp, "avatar", 10, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_profile_resp, "banner", 11, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_profile_resp, "followed_users", 13, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)
    add_f(msg_profile_resp, "joined_communities", 14, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)
    add_f(msg_profile_resp, "blocked_users", 15, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)
    add_f(msg_profile_resp, "blocked_posts", 16, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)
    add_f(msg_profile_resp, "blocked_communities", 17, descriptor_pb2.FieldDescriptorProto.TYPE_STRING, repeated=True)
    add_f(msg_profile_resp, "flair", 18, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    add_f(msg_profile_resp, "effective_paid", 19, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    def add_envelope(m):
        add_f(m, "authority", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
        add_f(m, "envelope_pubkey", 2, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
        add_f(m, "envelope_block_hash", 3, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
        add_f(m, "envelope_difficulty", 4, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
        add_f(m, "envelope_pow", 5, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
        add_f(m, "envelope_timestamp", 6, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
        add_f(m, "envelope_nonce", 7, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
        add_f(m, "envelope_signature", 10, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)

    STRING = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
    UINT64 = descriptor_pb2.FieldDescriptorProto.TYPE_UINT64
    UINT32 = descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
    BOOL = descriptor_pb2.FieldDescriptorProto.TYPE_BOOL
    INT64 = descriptor_pb2.FieldDescriptorProto.TYPE_INT64

    def add_msg_fields(name, fields):
        m = file_proto.message_type.add()
        m.name = name
        add_envelope(m)
        for fname, num, ftype, repeated in fields:
            add_f(m, fname, num, ftype, repeated=repeated)
        resp = file_proto.message_type.add()
        resp.name = name + "Response"

    add_msg_fields("MsgCreateCommunity", [
        ("community", 100, STRING, False),
        ("title", 101, STRING, False),
        ("description", 102, STRING, False),
        ("original_team_name", 103, STRING, False),
        ("bio", 104, STRING, False),
    ])
    add_msg_fields("MsgSetCommunityMetadata", [
        ("community", 100, STRING, False),
        ("title", 101, STRING, False),
        ("description", 102, STRING, False),
    ])
    add_msg_fields("MsgTransferCommunity", [
        ("community", 100, STRING, False),
        ("new_founder", 101, STRING, False),
    ])
    add_msg_fields("MsgJoinCommunity", [
        ("community", 100, STRING, False),
        ("mode", 101, UINT32, False),
        ("pinned_team_id", 102, UINT64, False),
    ])
    add_msg_fields("MsgLeaveCommunity", [("community", 100, STRING, False)])
    add_msg_fields("MsgBlockCommunity", [
        ("target", 100, STRING, False),
        ("community", 101, STRING, False),
    ])
    add_msg_fields("MsgUnblockCommunity", [
        ("target", 100, STRING, False),
        ("community", 101, STRING, False),
    ])
    add_msg_fields("MsgCreateCurationTeam", [
        ("community", 100, STRING, False),
        ("name", 101, STRING, False),
        ("description", 102, STRING, False),
    ])
    add_msg_fields("MsgSetCurationTeamProfile", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("name", 102, STRING, False),
        ("description", 103, STRING, False),
    ])
    add_msg_fields("MsgInviteCurator", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("target", 102, STRING, False),
    ])
    add_msg_fields("MsgRevokeCuratorInvite", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("target", 102, STRING, False),
    ])
    add_msg_fields("MsgAcceptCuratorInvite", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
    ])
    add_msg_fields("MsgDeclineCuratorInvite", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
    ])
    add_msg_fields("MsgLeaveCurationTeam", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
    ])
    add_msg_fields("MsgRemoveCurator", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("target", 102, STRING, False),
    ])
    add_msg_fields("MsgTransferCurationTeam", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("new_owner", 102, STRING, False),
    ])
    add_msg_fields("MsgDeleteCurationTeam", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
    ])
    add_msg_fields("MsgSetCurationPreference", [
        ("community", 100, STRING, False),
        ("mode", 101, UINT32, False),
        ("pinned_team_id", 102, UINT64, False),
    ])
    add_msg_fields("MsgSetCurationPostHidden", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("target", 102, STRING, False),
        ("hidden", 103, BOOL, False),
    ])
    add_msg_fields("MsgSetCurationUserHidden", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("target", 102, STRING, False),
        ("hidden", 103, BOOL, False),
    ])
    add_msg_fields("MsgSetCurationThreadLocked", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("root_hash", 102, STRING, False),
        ("locked", 103, BOOL, False),
    ])
    add_msg_fields("MsgSetCurationSubscriberOnly", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("enabled", 102, BOOL, False),
    ])
    add_msg_fields("MsgSetCurationTag", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("tag", 102, STRING, False),
    ])
    add_msg_fields("MsgSetCurationPostTag", [
        ("community", 100, STRING, False),
        ("team_id", 101, UINT64, False),
        ("target", 102, STRING, False),
        ("tag", 103, STRING, False),
        ("clear", 104, BOOL, False),
    ])
    claim = file_proto.message_type.add()
    claim.name = "MsgClaimCreatorRewards"
    add_envelope(claim)
    add_f(claim, "epoch_ids", 100, INT64, repeated=True)
    claim_resp = file_proto.message_type.add()
    claim_resp.name = "MsgClaimCreatorRewardsResponse"

    # cosmos.base.query.v1beta1 pagination types, needed by Query/GetProfiles.
    # Field numbers must match the upstream cosmos-sdk proto exactly.
    page_file = descriptor_pb2.FileDescriptorProto()
    page_file.name = "cosmos/base/query/v1beta1/pagination.proto"
    page_file.package = "cosmos.base.query.v1beta1"
    page_file.syntax = "proto3"

    page_req = page_file.message_type.add()
    page_req.name = "PageRequest"
    add_f(page_req, "key", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(page_req, "offset", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(page_req, "limit", 3, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)
    add_f(page_req, "count_total", 4, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)
    add_f(page_req, "reverse", 5, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    page_resp = page_file.message_type.add()
    page_resp.name = "PageResponse"
    add_f(page_resp, "next_key", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(page_resp, "total", 2, descriptor_pb2.FieldDescriptorProto.TYPE_UINT64)

    pool.Add(page_file)
    file_proto.dependency.append(page_file.name)

    curation_team = file_proto.message_type.add()
    curation_team.name = "CurationTeam"
    add_f(curation_team, "community", 1, STRING)
    add_f(curation_team, "team_id", 2, UINT64)
    add_f(curation_team, "owner", 3, STRING)
    add_f(curation_team, "name", 4, STRING)
    add_f(curation_team, "description", 5, STRING)
    # field 6 was policy — reserved; description carries moderation guidance
    add_f(curation_team, "subscriber_only", 8, BOOL)
    add_f(curation_team, "subscriber_count", 9, UINT64)
    add_f(curation_team, "created_height", 10, INT64)
    add_f(curation_team, "created_order", 11, UINT64)
    add_f(curation_team, "next_member_order", 12, UINT64)
    add_f(curation_team, "deleted_height", 13, INT64)
    add_f(curation_team, "tag", 14, STRING)

    curation_post_tag = file_proto.message_type.add()
    curation_post_tag.name = "CurationPostTag"
    add_f(curation_post_tag, "tag", 1, STRING)
    add_f(curation_post_tag, "actor", 2, STRING)
    add_f(curation_post_tag, "updated_height", 3, INT64)

    curation_member = file_proto.message_type.add()
    curation_member.name = "CurationTeamMember"
    add_f(curation_member, "address", 1, STRING)
    add_f(curation_member, "accepted_order", 2, UINT64)

    community_preference = file_proto.message_type.add()
    community_preference.name = "CommunityPreference"
    add_f(community_preference, "mode", 1, UINT32)
    add_f(community_preference, "pinned_team_id", 2, UINT64)

    def add_message_field(message, name, number, type_name, *, repeated=False):
        field = message.field.add()
        field.name = name
        field.number = number
        field.label = (
            descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
            if repeated
            else descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        )
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
        field.type_name = type_name

    query_team_req = file_proto.message_type.add()
    query_team_req.name = "QueryCurationTeamRequest"
    add_f(query_team_req, "community", 1, STRING)
    add_f(query_team_req, "team_id", 2, UINT64)
    query_team_resp = file_proto.message_type.add()
    query_team_resp.name = "QueryCurationTeamResponse"
    add_message_field(query_team_resp, "team", 1, ".mirage.core.v1.CurationTeam")

    query_teams_req = file_proto.message_type.add()
    query_teams_req.name = "QueryCurationTeamsRequest"
    add_f(query_teams_req, "community", 1, STRING)
    add_f(query_teams_req, "include_deleted", 2, BOOL)
    add_message_field(query_teams_req, "pagination", 3, ".cosmos.base.query.v1beta1.PageRequest")
    query_teams_resp = file_proto.message_type.add()
    query_teams_resp.name = "QueryCurationTeamsResponse"
    add_message_field(query_teams_resp, "teams", 1, ".mirage.core.v1.CurationTeam", repeated=True)
    add_message_field(query_teams_resp, "pagination", 2, ".cosmos.base.query.v1beta1.PageResponse")

    query_all_teams_req = file_proto.message_type.add()
    query_all_teams_req.name = "QueryAllCurationTeamsRequest"
    add_f(query_all_teams_req, "include_deleted", 1, BOOL)
    add_message_field(query_all_teams_req, "pagination", 2, ".cosmos.base.query.v1beta1.PageRequest")
    query_all_teams_resp = file_proto.message_type.add()
    query_all_teams_resp.name = "QueryAllCurationTeamsResponse"
    add_message_field(query_all_teams_resp, "teams", 1, ".mirage.core.v1.CurationTeam", repeated=True)
    add_message_field(query_all_teams_resp, "pagination", 2, ".cosmos.base.query.v1beta1.PageResponse")

    query_members_req = file_proto.message_type.add()
    query_members_req.name = "QueryCurationTeamMembersRequest"
    add_f(query_members_req, "community", 1, STRING)
    add_f(query_members_req, "team_id", 2, UINT64)
    add_message_field(query_members_req, "pagination", 3, ".cosmos.base.query.v1beta1.PageRequest")
    query_members_resp = file_proto.message_type.add()
    query_members_resp.name = "QueryCurationTeamMembersResponse"
    add_message_field(
        query_members_resp, "members", 1, ".mirage.core.v1.CurationTeamMember", repeated=True
    )
    add_message_field(query_members_resp, "pagination", 2, ".cosmos.base.query.v1beta1.PageResponse")

    pending_invitation = file_proto.message_type.add()
    pending_invitation.name = "PendingCuratorInvitation"
    add_f(pending_invitation, "community", 1, STRING)
    add_f(pending_invitation, "team_id", 2, UINT64)
    add_f(pending_invitation, "invitee", 3, STRING)
    add_f(pending_invitation, "inviter", 4, STRING)

    query_invitations_req = file_proto.message_type.add()
    query_invitations_req.name = "QueryPendingCuratorInvitationsRequest"
    add_f(query_invitations_req, "address", 1, STRING)
    add_message_field(query_invitations_req, "pagination", 2, ".cosmos.base.query.v1beta1.PageRequest")
    query_invitations_resp = file_proto.message_type.add()
    query_invitations_resp.name = "QueryPendingCuratorInvitationsResponse"
    add_message_field(
        query_invitations_resp,
        "invitations",
        1,
        ".mirage.core.v1.PendingCuratorInvitation",
        repeated=True,
    )
    add_message_field(query_invitations_resp, "pagination", 2, ".cosmos.base.query.v1beta1.PageResponse")

    curation_membership = file_proto.message_type.add()
    curation_membership.name = "CurationMembership"
    add_f(curation_membership, "community", 1, STRING)
    add_f(curation_membership, "team_id", 2, UINT64)

    query_memberships_req = file_proto.message_type.add()
    query_memberships_req.name = "QueryCurationMembershipsRequest"
    add_f(query_memberships_req, "address", 1, STRING)
    add_message_field(query_memberships_req, "pagination", 2, ".cosmos.base.query.v1beta1.PageRequest")
    query_memberships_resp = file_proto.message_type.add()
    query_memberships_resp.name = "QueryCurationMembershipsResponse"
    add_message_field(
        query_memberships_resp,
        "memberships",
        1,
        ".mirage.core.v1.CurationMembership",
        repeated=True,
    )
    add_message_field(query_memberships_resp, "pagination", 2, ".cosmos.base.query.v1beta1.PageResponse")

    query_pref_req = file_proto.message_type.add()
    query_pref_req.name = "QueryCommunityPreferenceRequest"
    add_f(query_pref_req, "owner", 1, STRING)
    add_f(query_pref_req, "community", 2, STRING)
    query_pref_resp = file_proto.message_type.add()
    query_pref_resp.name = "QueryCommunityPreferenceResponse"
    add_message_field(query_pref_resp, "stored", 1, ".mirage.core.v1.CommunityPreference")
    # CurationPreferenceMode is a proto3 enum, so the mirror reads it as the
    # varint it is on the wire.
    add_f(query_pref_resp, "effective_mode", 2, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    add_f(query_pref_resp, "effective_team_id", 3, UINT64)

    post_metadata = file_proto.message_type.add()
    post_metadata.name = "PostMetadata"
    add_f(post_metadata, "author", 1, STRING)
    add_f(post_metadata, "parent_hash", 2, STRING)
    add_f(post_metadata, "root_hash", 3, STRING)
    add_f(post_metadata, "community", 4, STRING)
    add_f(post_metadata, "global_sequence", 5, UINT64)
    add_f(post_metadata, "created_height", 6, INT64)
    add_f(post_metadata, "created_epoch", 7, INT64)
    add_f(post_metadata, "was_subscriber_at_creation", 8, BOOL)
    add_f(post_metadata, "deleted_height", 9, INT64)
    add_f(post_metadata, "deleted_epoch", 10, INT64)
    add_f(post_metadata, "deletion_actor", 11, STRING)

    query_post_meta_req = file_proto.message_type.add()
    query_post_meta_req.name = "QueryPostMetadataRequest"
    add_f(query_post_meta_req, "txhash", 1, STRING)
    query_post_meta_resp = file_proto.message_type.add()
    query_post_meta_resp.name = "QueryPostMetadataResponse"
    add_message_field(query_post_meta_resp, "metadata", 1, ".mirage.core.v1.PostMetadata")

    creator_epoch = file_proto.message_type.add()
    creator_epoch.name = "CreatorEpoch"
    add_f(creator_epoch, "epoch_id", 1, INT64)
    add_f(creator_epoch, "pool", 2, STRING)
    add_f(creator_epoch, "status", 3, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    add_f(creator_epoch, "phase", 4, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    add_f(creator_epoch, "gross_records", 5, UINT64)
    add_f(creator_epoch, "active_engagers", 6, UINT64)
    add_f(creator_epoch, "engager_slice", 7, STRING)
    add_f(creator_epoch, "allocated_total", 8, STRING)
    add_f(creator_epoch, "claimed_total", 9, STRING)
    add_f(creator_epoch, "finalized_epoch", 10, INT64)
    add_f(creator_epoch, "claim_window_days", 11, INT64)
    add_f(creator_epoch, "claim_deadline_unix", 12, INT64)
    add_f(creator_epoch, "start_unix", 18, INT64)
    add_f(creator_epoch, "end_unix", 19, INT64)
    add_f(creator_epoch, "settlement_cursor", 13, descriptor_pb2.FieldDescriptorProto.TYPE_BYTES)
    add_f(creator_epoch, "partial_actor", 14, STRING)
    add_f(creator_epoch, "partial_count", 15, UINT64)
    add_f(creator_epoch, "prune_pending", 16, BOOL)
    add_f(creator_epoch, "prune_complete", 17, BOOL)

    creator_accrual = file_proto.message_type.add()
    creator_accrual.name = "CreatorAccrual"
    add_f(creator_accrual, "epoch", 1, INT64)
    add_f(creator_accrual, "creator", 2, STRING)
    add_f(creator_accrual, "amount", 3, STRING)
    add_f(creator_accrual, "claimed_amount", 4, STRING)
    add_f(creator_accrual, "claimed", 5, BOOL)
    add_f(creator_accrual, "claimed_height", 6, INT64)
    add_f(creator_accrual, "claimed_txhash", 7, STRING)

    query_creator_epoch_req = file_proto.message_type.add()
    query_creator_epoch_req.name = "QueryCreatorEpochRequest"
    add_f(query_creator_epoch_req, "epoch_id", 1, INT64)
    query_creator_epoch_resp = file_proto.message_type.add()
    query_creator_epoch_resp.name = "QueryCreatorEpochResponse"
    add_message_field(query_creator_epoch_resp, "epoch", 1, ".mirage.core.v1.CreatorEpoch")

    query_epoch_accruals_req = file_proto.message_type.add()
    query_epoch_accruals_req.name = "QueryCreatorEpochAccrualsRequest"
    add_f(query_epoch_accruals_req, "epoch_id", 1, INT64)
    add_message_field(query_epoch_accruals_req, "pagination", 2, ".cosmos.base.query.v1beta1.PageRequest")
    query_epoch_accruals_resp = file_proto.message_type.add()
    query_epoch_accruals_resp.name = "QueryCreatorEpochAccrualsResponse"
    add_message_field(
        query_epoch_accruals_resp,
        "accruals",
        1,
        ".mirage.core.v1.CreatorAccrual",
        repeated=True,
    )
    add_message_field(
        query_epoch_accruals_resp,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageResponse",
    )

    target_earning = file_proto.message_type.add()
    target_earning.name = "TargetEarning"
    add_f(target_earning, "epoch_id", 1, INT64)
    add_f(target_earning, "target", 2, STRING)
    add_f(target_earning, "creator", 3, STRING)
    add_f(target_earning, "upvote_units", 4, UINT64)
    add_f(target_earning, "direct_reply_units", 5, UINT64)
    add_f(target_earning, "amount", 6, STRING)

    query_epoch_targets_req = file_proto.message_type.add()
    query_epoch_targets_req.name = "QueryCreatorEpochTargetsRequest"
    add_f(query_epoch_targets_req, "epoch_id", 1, INT64)
    add_message_field(query_epoch_targets_req, "pagination", 2, ".cosmos.base.query.v1beta1.PageRequest")
    query_epoch_targets_resp = file_proto.message_type.add()
    query_epoch_targets_resp.name = "QueryCreatorEpochTargetsResponse"
    add_message_field(
        query_epoch_targets_resp,
        "earnings",
        1,
        ".mirage.core.v1.TargetEarning",
        repeated=True,
    )
    add_message_field(
        query_epoch_targets_resp,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageResponse",
    )

    renewal_state = file_proto.message_type.add()
    renewal_state.name = "SubscriptionRenewalState"
    add_f(renewal_state, "expiry", 1, INT64)
    add_f(renewal_state, "next_attempt_unix", 2, INT64)
    add_f(renewal_state, "last_attempt_epoch", 3, INT64)
    add_f(renewal_state, "warning_sent", 4, BOOL)
    add_f(renewal_state, "generation", 5, UINT64)

    query_renewal_req = file_proto.message_type.add()
    query_renewal_req.name = "QuerySubscriptionRenewalRequest"
    add_f(query_renewal_req, "address", 1, STRING)
    query_renewal_resp = file_proto.message_type.add()
    query_renewal_resp.name = "QuerySubscriptionRenewalResponse"
    add_message_field(query_renewal_resp, "state", 1, ".mirage.core.v1.SubscriptionRenewalState")
    add_f(query_renewal_resp, "curation_membership_count", 2, UINT32)

    query_quota_req = file_proto.message_type.add()
    query_quota_req.name = "QuerySubscriberQuotaRequest"
    add_f(query_quota_req, "address", 1, STRING)
    query_quota_resp = file_proto.message_type.add()
    query_quota_resp.name = "QuerySubscriberQuotaResponse"
    add_f(query_quota_resp, "epoch", 1, INT64)
    add_f(query_quota_resp, "limit", 2, UINT64)
    add_f(query_quota_resp, "used", 3, UINT64)
    add_f(query_quota_resp, "remaining", 4, UINT64)
    add_f(query_quota_resp, "reset_at", 5, INT64)

    query_schedule_req = file_proto.message_type.add()
    query_schedule_req.name = "QueryCreatorScheduleRequest"
    query_schedule_resp = file_proto.message_type.add()
    query_schedule_resp.name = "QueryCreatorScheduleResponse"
    add_f(query_schedule_resp, "origin_epoch", 1, INT64)
    add_f(query_schedule_resp, "origin_unix", 2, INT64)
    add_f(query_schedule_resp, "epoch_seconds", 3, UINT64)
    add_f(query_schedule_resp, "current_epoch", 4, INT64)

    query_terminal_epochs_req = file_proto.message_type.add()
    query_terminal_epochs_req.name = "QueryTerminalCreatorEpochsRequest"
    add_f(query_terminal_epochs_req, "cutoff_deadline_unix", 1, INT64)
    add_message_field(
        query_terminal_epochs_req,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageRequest",
    )
    query_terminal_epochs_resp = file_proto.message_type.add()
    query_terminal_epochs_resp.name = "QueryTerminalCreatorEpochsResponse"
    add_message_field(
        query_terminal_epochs_resp,
        "epochs",
        1,
        ".mirage.core.v1.CreatorEpoch",
        repeated=True,
    )
    add_message_field(
        query_terminal_epochs_resp,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageResponse",
    )

    subscription_tranche = file_proto.message_type.add()
    subscription_tranche.name = "SubscriptionTranche"
    add_f(subscription_tranche, "id", 1, UINT64)
    add_f(subscription_tranche, "payer", 2, STRING)
    add_f(subscription_tranche, "recipient", 3, STRING)
    add_f(subscription_tranche, "source", 4, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    add_f(subscription_tranche, "start_time", 5, INT64)
    add_f(subscription_tranche, "end_time", 6, INT64)
    add_f(subscription_tranche, "period_count", 7, UINT32)
    add_f(subscription_tranche, "total_fee", 8, STRING)
    add_f(subscription_tranche, "burn_amount", 9, STRING)
    add_f(subscription_tranche, "creator_amount", 10, STRING)
    add_f(subscription_tranche, "creator_bps", 11, UINT64)
    add_f(subscription_tranche, "period", 12, UINT64)
    add_f(subscription_tranche, "created_height", 13, INT64)
    add_f(subscription_tranche, "txhash", 14, STRING)

    query_tranches_req = file_proto.message_type.add()
    query_tranches_req.name = "QuerySubscriptionTranchesRequest"
    add_f(query_tranches_req, "address", 1, STRING)
    add_message_field(
        query_tranches_req,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageRequest",
    )
    query_tranches_resp = file_proto.message_type.add()
    query_tranches_resp.name = "QuerySubscriptionTranchesResponse"
    add_message_field(
        query_tranches_resp,
        "tranches",
        1,
        ".mirage.core.v1.SubscriptionTranche",
        repeated=True,
    )
    add_message_field(
        query_tranches_resp,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageResponse",
    )

    query_creator_accruals_req = file_proto.message_type.add()
    query_creator_accruals_req.name = "QueryCreatorAccrualsRequest"
    add_f(query_creator_accruals_req, "creator", 1, STRING)
    add_message_field(
        query_creator_accruals_req,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageRequest",
    )
    query_creator_accruals_resp = file_proto.message_type.add()
    query_creator_accruals_resp.name = "QueryCreatorAccrualsResponse"
    add_message_field(
        query_creator_accruals_resp,
        "accruals",
        1,
        ".mirage.core.v1.CreatorAccrual",
        repeated=True,
    )
    add_message_field(
        query_creator_accruals_resp,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageResponse",
    )

    query_target_earnings_req = file_proto.message_type.add()
    query_target_earnings_req.name = "QueryTargetEarningsRequest"
    add_f(query_target_earnings_req, "target", 1, STRING)
    add_message_field(
        query_target_earnings_req,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageRequest",
    )
    query_target_earnings_resp = file_proto.message_type.add()
    query_target_earnings_resp.name = "QueryTargetEarningsResponse"
    add_message_field(
        query_target_earnings_resp,
        "earnings",
        1,
        ".mirage.core.v1.TargetEarning",
        repeated=True,
    )
    add_message_field(
        query_target_earnings_resp,
        "pagination",
        2,
        ".cosmos.base.query.v1beta1.PageResponse",
    )

    # QueryProfilesRequest
    msg_profiles_req = file_proto.message_type.add()
    msg_profiles_req.name = "QueryProfilesRequest"
    f = msg_profiles_req.field.add()
    f.name = "pagination"
    f.number = 1
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f.type_name = ".cosmos.base.query.v1beta1.PageRequest"

    # QueryProfilesResponse
    msg_profiles_resp = file_proto.message_type.add()
    msg_profiles_resp.name = "QueryProfilesResponse"
    f = msg_profiles_resp.field.add()
    f.name = "profiles"
    f.number = 1
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
    f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f.type_name = ".mirage.core.v1.QueryProfileResponse"
    f = msg_profiles_resp.field.add()
    f.name = "pagination"
    f.number = 2
    f.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    f.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
    f.type_name = ".cosmos.base.query.v1beta1.PageResponse"

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
MsgAnnotate = _get_message_class("mirage.core.v1.MsgAnnotate")
MsgVote = _get_message_class("mirage.core.v1.MsgVote")
MsgSetUsername = _get_message_class("mirage.core.v1.MsgSetUsername")
MsgSetBiography = _get_message_class("mirage.core.v1.MsgSetBiography")
MsgEnableAgent = _get_message_class("mirage.core.v1.MsgEnableAgent")
MsgDisableAgent = _get_message_class("mirage.core.v1.MsgDisableAgent")
MsgSetAgents = _get_message_class("mirage.core.v1.MsgSetAgents")
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
MsgSubscribe = _get_message_class("mirage.core.v1.MsgSubscribe")
MsgSetAutoRenewal = _get_message_class("mirage.core.v1.MsgSetAutoRenewal")
MsgAward = _get_message_class("mirage.core.v1.MsgAward")
MsgAwardResponse = _get_message_class("mirage.core.v1.MsgAwardResponse")
AwardConfig = _get_message_class("mirage.core.v1.AwardConfig")
TierConfig = _get_message_class("mirage.core.v1.TierConfig")
Params = _get_message_class("mirage.core.v1.Params")
MsgUpdateParams = _get_message_class("mirage.core.v1.MsgUpdateParams")
QueryParamsRequest = _get_message_class("mirage.core.v1.QueryParamsRequest")
QueryParamsResponse = _get_message_class("mirage.core.v1.QueryParamsResponse")
QueryDifficultyRequest = _get_message_class("mirage.core.v1.QueryDifficultyRequest")
QueryDifficultyResponse = _get_message_class("mirage.core.v1.QueryDifficultyResponse")
QueryProfileRequest = _get_message_class("mirage.core.v1.QueryProfileRequest")
QueryProfileResponse = _get_message_class("mirage.core.v1.QueryProfileResponse")
QueryProfilesRequest = _get_message_class("mirage.core.v1.QueryProfilesRequest")
QueryProfilesResponse = _get_message_class("mirage.core.v1.QueryProfilesResponse")
PageRequest = _get_message_class("cosmos.base.query.v1beta1.PageRequest")
PageResponse = _get_message_class("cosmos.base.query.v1beta1.PageResponse")
MsgCreateCommunity = _get_message_class("mirage.core.v1.MsgCreateCommunity")
MsgSetCommunityMetadata = _get_message_class("mirage.core.v1.MsgSetCommunityMetadata")
MsgTransferCommunity = _get_message_class("mirage.core.v1.MsgTransferCommunity")
MsgJoinCommunity = _get_message_class("mirage.core.v1.MsgJoinCommunity")
MsgLeaveCommunity = _get_message_class("mirage.core.v1.MsgLeaveCommunity")
MsgBlockCommunity = _get_message_class("mirage.core.v1.MsgBlockCommunity")
MsgUnblockCommunity = _get_message_class("mirage.core.v1.MsgUnblockCommunity")
MsgCreateCurationTeam = _get_message_class("mirage.core.v1.MsgCreateCurationTeam")
MsgSetCurationTeamProfile = _get_message_class("mirage.core.v1.MsgSetCurationTeamProfile")
MsgInviteCurator = _get_message_class("mirage.core.v1.MsgInviteCurator")
MsgRevokeCuratorInvite = _get_message_class("mirage.core.v1.MsgRevokeCuratorInvite")
MsgAcceptCuratorInvite = _get_message_class("mirage.core.v1.MsgAcceptCuratorInvite")
MsgDeclineCuratorInvite = _get_message_class("mirage.core.v1.MsgDeclineCuratorInvite")
MsgLeaveCurationTeam = _get_message_class("mirage.core.v1.MsgLeaveCurationTeam")
MsgRemoveCurator = _get_message_class("mirage.core.v1.MsgRemoveCurator")
MsgTransferCurationTeam = _get_message_class("mirage.core.v1.MsgTransferCurationTeam")
MsgDeleteCurationTeam = _get_message_class("mirage.core.v1.MsgDeleteCurationTeam")
MsgSetCurationPreference = _get_message_class("mirage.core.v1.MsgSetCurationPreference")
MsgSetCurationPostHidden = _get_message_class("mirage.core.v1.MsgSetCurationPostHidden")
MsgSetCurationUserHidden = _get_message_class("mirage.core.v1.MsgSetCurationUserHidden")
MsgSetCurationThreadLocked = _get_message_class("mirage.core.v1.MsgSetCurationThreadLocked")
MsgSetCurationSubscriberOnly = _get_message_class("mirage.core.v1.MsgSetCurationSubscriberOnly")
MsgSetCurationTag = _get_message_class("mirage.core.v1.MsgSetCurationTag")
MsgSetCurationPostTag = _get_message_class("mirage.core.v1.MsgSetCurationPostTag")
MsgClaimCreatorRewards = _get_message_class("mirage.core.v1.MsgClaimCreatorRewards")
CurationTeam = _get_message_class("mirage.core.v1.CurationTeam")
CurationPostTag = _get_message_class("mirage.core.v1.CurationPostTag")
CurationTeamMember = _get_message_class("mirage.core.v1.CurationTeamMember")
CommunityPreference = _get_message_class("mirage.core.v1.CommunityPreference")
QueryCurationTeamRequest = _get_message_class("mirage.core.v1.QueryCurationTeamRequest")
QueryCurationTeamResponse = _get_message_class("mirage.core.v1.QueryCurationTeamResponse")
QueryCurationTeamsRequest = _get_message_class("mirage.core.v1.QueryCurationTeamsRequest")
QueryCurationTeamsResponse = _get_message_class("mirage.core.v1.QueryCurationTeamsResponse")
QueryAllCurationTeamsRequest = _get_message_class("mirage.core.v1.QueryAllCurationTeamsRequest")
QueryAllCurationTeamsResponse = _get_message_class("mirage.core.v1.QueryAllCurationTeamsResponse")
QueryCurationTeamMembersRequest = _get_message_class("mirage.core.v1.QueryCurationTeamMembersRequest")
QueryCurationTeamMembersResponse = _get_message_class("mirage.core.v1.QueryCurationTeamMembersResponse")
PendingCuratorInvitation = _get_message_class("mirage.core.v1.PendingCuratorInvitation")
QueryPendingCuratorInvitationsRequest = _get_message_class(
    "mirage.core.v1.QueryPendingCuratorInvitationsRequest"
)
QueryPendingCuratorInvitationsResponse = _get_message_class(
    "mirage.core.v1.QueryPendingCuratorInvitationsResponse"
)
CurationMembership = _get_message_class("mirage.core.v1.CurationMembership")
QueryCurationMembershipsRequest = _get_message_class("mirage.core.v1.QueryCurationMembershipsRequest")
QueryCurationMembershipsResponse = _get_message_class("mirage.core.v1.QueryCurationMembershipsResponse")
QueryCommunityPreferenceRequest = _get_message_class("mirage.core.v1.QueryCommunityPreferenceRequest")
QueryCommunityPreferenceResponse = _get_message_class("mirage.core.v1.QueryCommunityPreferenceResponse")
PostMetadata = _get_message_class("mirage.core.v1.PostMetadata")
QueryPostMetadataRequest = _get_message_class("mirage.core.v1.QueryPostMetadataRequest")
QueryPostMetadataResponse = _get_message_class("mirage.core.v1.QueryPostMetadataResponse")
CreatorEpoch = _get_message_class("mirage.core.v1.CreatorEpoch")
CreatorAccrual = _get_message_class("mirage.core.v1.CreatorAccrual")
QueryCreatorEpochRequest = _get_message_class("mirage.core.v1.QueryCreatorEpochRequest")
QueryCreatorEpochResponse = _get_message_class("mirage.core.v1.QueryCreatorEpochResponse")
QueryCreatorEpochAccrualsRequest = _get_message_class("mirage.core.v1.QueryCreatorEpochAccrualsRequest")
QueryCreatorEpochAccrualsResponse = _get_message_class("mirage.core.v1.QueryCreatorEpochAccrualsResponse")
TargetEarning = _get_message_class("mirage.core.v1.TargetEarning")
QueryCreatorEpochTargetsRequest = _get_message_class("mirage.core.v1.QueryCreatorEpochTargetsRequest")
QueryCreatorEpochTargetsResponse = _get_message_class("mirage.core.v1.QueryCreatorEpochTargetsResponse")
SubscriptionRenewalState = _get_message_class("mirage.core.v1.SubscriptionRenewalState")
QuerySubscriptionRenewalRequest = _get_message_class("mirage.core.v1.QuerySubscriptionRenewalRequest")
QuerySubscriptionRenewalResponse = _get_message_class("mirage.core.v1.QuerySubscriptionRenewalResponse")
QuerySubscriberQuotaRequest = _get_message_class("mirage.core.v1.QuerySubscriberQuotaRequest")
QuerySubscriberQuotaResponse = _get_message_class("mirage.core.v1.QuerySubscriberQuotaResponse")
QueryCreatorScheduleRequest = _get_message_class("mirage.core.v1.QueryCreatorScheduleRequest")
QueryCreatorScheduleResponse = _get_message_class("mirage.core.v1.QueryCreatorScheduleResponse")
QueryTerminalCreatorEpochsRequest = _get_message_class("mirage.core.v1.QueryTerminalCreatorEpochsRequest")
QueryTerminalCreatorEpochsResponse = _get_message_class("mirage.core.v1.QueryTerminalCreatorEpochsResponse")
SubscriptionTranche = _get_message_class("mirage.core.v1.SubscriptionTranche")
QuerySubscriptionTranchesRequest = _get_message_class("mirage.core.v1.QuerySubscriptionTranchesRequest")
QuerySubscriptionTranchesResponse = _get_message_class("mirage.core.v1.QuerySubscriptionTranchesResponse")
QueryCreatorAccrualsRequest = _get_message_class("mirage.core.v1.QueryCreatorAccrualsRequest")
QueryCreatorAccrualsResponse = _get_message_class("mirage.core.v1.QueryCreatorAccrualsResponse")
QueryTargetEarningsRequest = _get_message_class("mirage.core.v1.QueryTargetEarningsRequest")
QueryTargetEarningsResponse = _get_message_class("mirage.core.v1.QueryTargetEarningsResponse")
