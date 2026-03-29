/**
 * Centralized error message mapping.
 *
 * Backend returns { error: "human readable", error_code: "snake_case" }.
 * UI must display messages based on error_code only (no string fallbacks).
 */

const ERROR_MAP = {
    // Registration / signup
    registration_disabled: "Registration is currently disabled on this node.",
    invite_code_required: "An invite code is required to create an account.",
    invite_code_invalid: "That invite code is not valid.",
    invite_code_used: "That invite code has already been used.",
    invite_code_check_failed: "Could not validate the invite code. Please try again.",
    invite_code_invalid_format: "Invite code format is invalid.",
    invite_codes_not_required: "Invite codes are not required on this node.",
    invite_codes_main_site_only: "Invite codes only work on mirage.talk.",

    // Username
    username_required: "A username is required.",
    username_too_short: "Your username is too short.",
    username_too_long: "Your username is too long.",
    username_invalid_format: "Usernames can only contain letters, numbers, and hyphens.",
    username_taken: "That username is already taken.",

    // Referrals
    referral_requires_invite_codes: "Referral links require invite codes to be enabled.",
    referrer_not_found: "Referrer not found.",
    referrer_not_opted_in: "This referrer has not enabled referral links.",
    referrer_no_codes: "This referrer has no invite codes left.",
    referrer_already_used: "You already used this referrer.",
    referrer_username_too_long: "Referrer username is too long.",
    referrer_username_invalid_format: "Invalid referrer username format.",
    referrer_check_failed: "Could not validate the referrer. Please try again.",
    self_referral: "You cannot refer yourself.",

    // Auth / envelope
    missing_fields: "Missing required fields.",
    invalid_pubkey: "Invalid public key.",
    invalid_signature: "Invalid signature.",
    invalid_timestamp: "Invalid timestamp.",
    timestamp_required: "Timestamp is required.",
    timestamp_must_be_millis: "Timestamp must be in milliseconds.",
    timestamp_outside_window: "Timestamp is outside the allowed window.",
    invalid_nonce: "Invalid envelope nonce.",
    nonce_required: "Envelope nonce is required.",
    nonce_must_be_positive: "Envelope nonce must be positive.",
    nonce_out_of_range: "Envelope nonce exceeds allowed range.",
    nonce_replayed: "This request has already been processed.",
    invalid_relay_fields: "Invalid relay fields.",
    invalid_owner: "Invalid owner.",
    enabled_must_be_boolean: "Enabled must be a boolean.",
    address_mismatch: "Address does not match the provided key.",
    address_required: "Address is required.",
    control_characters: "Fields contain invalid control characters.",
    forbidden: "You do not have permission to perform this action.",
    unauthorized: "Unauthorized.",

    // Server state
    node_catching_up: "The node is syncing. Please try again shortly.",
    backend_not_initialized: "The server is starting up. Please try again shortly.",
    indexer_unavailable: "Data service is temporarily unavailable.",
    internal_error: "Something went wrong. Please try again.",
    debug_localhost_only: "Debug endpoints are only available on localhost.",

    // PoW
    insufficient_pow_precheck: "Proof-of-work is insufficient. Please try again.",
    pow_not_allowed_agents: "Proof-of-work is not allowed for agents.",
    pow_not_allowed_for_award: "Proof-of-work is not allowed for awards.",
    pow_not_allowed_for_set_auto_renewal: "Proof-of-work is not allowed for auto-renewal.",
    pow_required: "Proof-of-work is required.",
    invalid_pow_fields: "Invalid proof-of-work fields.",
    invalid_last_block_hash: "Invalid last block hash.",
    pow_timeout: "Proof-of-work took too long. Please try again later.",
    pow_worker_failed: "Proof-of-work failed. Please try again.",
    pow_worker_invalid_response: "Proof-of-work failed due to an invalid worker response.",

    // Content / posts
    title_too_long: "Your title exceeds the maximum length.",
    content_too_long: "Your post exceeds the maximum length.",
    topic_too_short: "Topic name is too short.",
    topic_too_long: "Topic name is too long.",
    topic_invalid_format: "Topic name contains invalid characters.",
    topic_required: "A topic is required for new posts.",
    comment_content_required: "Comment text is required.",
    comment_not_found: "Comment not found.",
    post_not_found: "Post not found.",
    invalid_target: "Invalid target.",
    invalid_target_format: "Invalid target format.",
    target_not_found: "The target post or comment was not found.",
    target_mismatch: "Cannot change the parent of an existing post.",
    comment_must_not_include_topic: "Comments must not include a topic.",
    tag_too_long: "Tag is too long.",
    invalid_tag: "Invalid tag.",
    invalid_override: "Invalid override.",
    post_id_required: "Post ID is required.",
    comment_id_required: "Comment ID is required.",
    invalid_hash: "Invalid or missing hash.",
    target_must_be_mirage1: "Target must be a valid mirage1 address.",

    // Media
    media_not_list: "Media must be provided as a list.",
    media_limit_exceeded: "Too many media attachments.",
    media_item_too_long: "A media URL is too long.",
    media_must_use_https: "Media URLs must use HTTPS.",
    media_control_characters: "Media contains invalid control characters.",

    // Biography
    biography_too_long: "Your biography exceeds the maximum length.",

    // Blocks / follows
    cannot_block_self: "You cannot block yourself.",
    cannot_follow_self: "You cannot follow yourself.",
    post_already_blocked: "You already blocked this post.",
    user_already_blocked: "You already blocked this user.",
    topic_already_blocked: "You already blocked this topic.",
    user_already_followed: "You already follow this user.",
    topic_already_followed: "You already follow this topic.",
    user_must_be_mirage1: "User must be a valid mirage1 address.",
    block_post_in_progress: "Block post request already in progress.",
    unblock_post_in_progress: "Unblock post request already in progress.",
    block_user_in_progress: "Block user request already in progress.",
    unblock_user_in_progress: "Unblock user request already in progress.",
    block_topic_in_progress: "Block topic request already in progress.",
    unblock_topic_in_progress: "Unblock topic request already in progress.",
    follow_user_in_progress: "Follow user request already in progress.",
    unfollow_user_in_progress: "Unfollow user request already in progress.",
    follow_topic_in_progress: "Follow topic request already in progress.",
    unfollow_topic_in_progress: "Unfollow topic request already in progress.",
    vote_already_pending: "Vote already pending.",
    delete_in_progress: "Delete account request already in progress.",

    // Agents
    invalid_agent_address: "Invalid agent address.",
    duplicate_agent: "Duplicate agent in the list.",
    too_many_agents: "You have too many agents enabled.",
    agents_must_be_array: "Agents must be provided as a list.",
    agent_already_enabled: "This agent is already enabled.",
    cannot_enable_self_as_agent: "You cannot enable yourself as an agent.",
    cannot_set_self_as_agent: "You cannot set yourself as an agent.",
    agent_tier_required: "Agent features require a higher subscription tier.",
    missing_tier_config: "Agent tier configuration is missing.",
    missing_profile_level: "Profile level is missing.",
    missing_max_agents: "Max enabled agents is missing.",
    enable_agent_in_progress: "Enable agent request already in progress.",
    disable_agent_in_progress: "Disable agent request already in progress.",
    agent_address_required: "Agent address is required.",

    // Subscription
    not_subscriber: "This action requires an active subscription.",
    invalid_level: "Invalid subscription level.",
    insufficient_balance: "Insufficient balance to complete this transaction.",
    admin_insufficient_balance: "Your account balance is too low to cover the transaction fee.",
    insufficient_funds: "Node does not have enough gas for this transaction.",
    auto_renew_required: "Auto-renewal setting is required.",

    // Awards
    cannot_award_own_post: "You cannot award your own post.",
    already_awarded: "You already awarded this post.",
    award_eligibility_failed: "Unable to verify award eligibility.",
    unknown_award_type: "Unknown award type.",
    award_missing_target_or_type: "Award target and type are required.",

    // Push notifications
    push_disabled: "Push notifications are not enabled on this node.",
    push_invalid_token: "Invalid push notification token format.",
    push_token_length: "Invalid push notification token length.",
    push_invalid_platform: "Push platform must be ios or android.",
    push_token_other_account: "This push token is registered to another account.",

    // Reports / moderation
    reason_too_long: "Report reason is too long (max 200 characters).",
    admin_required: "Admin address is required.",
    admin_and_target_required: "Admin and target are required.",
    admin_target_duration_reason_required: "Admin, target, duration, and reason are required.",
    owner_required: "Owner is required.",
    suspended: "Your account is suspended.",

    // Search / query
    query_required: "Query parameter is required.",
    count_must_be_non_negative: "Count must be non-negative.",
    invalid_amount: "Invalid amount.",
    amount_must_be_positive: "Amount must be positive.",
    amount_too_small: "Amount is below the minimum.",
    invalid_duration_days: "Invalid duration.",
    invalid_month_format: "Invalid month format (use YYYY-MM).",
    invalid_max_depth: "Invalid max depth.",
    unsupported_sort_mode: "Unsupported sort mode.",

    // Bridge / upload
    destination_chain_required: "Destination chain is required.",
    destination_address_required: "Destination address is required.",
    destination_chain_not_enabled: "Destination chain is not enabled.",
    destination_chain_too_long: "Destination chain is too long.",
    destination_address_too_long: "Destination address is too long.",
    invalid_solana_address: "Invalid Solana address.",
    invalid_solana_address_length: "Invalid Solana address length.",
    burn_sequence_required: "Burn sequence is required.",
    burn_tx_hash_required: "Burn tx hash is required.",
    burn_sequence_not_allowed_outbound: "Burn sequence is not allowed for outbound queries.",
    burn_tx_hash_not_allowed_inbound: "Burn tx hash is not allowed for inbound queries.",
    invalid_burn_tx_hash: "Invalid burn tx hash.",
    upload_service_error: "Upload service encountered an error.",
    cloudflare_not_configured: "Upload service is not configured.",
    cloudflare_stream_not_configured: "Stream upload service is not configured.",
    cloudflare_no_url: "Upload service did not return a URL.",
    cloudflare_stream_no_url: "Stream upload service did not return a URL.",
    image_type_only: "Only image uploads are supported.",
    invalid_video_uid: "Invalid video UID.",
    not_configured: "Service is not configured.",
    pool_not_configured: "Pool is not configured.",
    no_rewards: "No rewards available.",
    payout_failed: "Payout failed.",
    retry: "Please retry the request.",
    stats_event_disabled: "Stats events are disabled on this node.",
    invalid_user_level: "Invalid user level.",

    // Quests
    quest_id_required: "Quest ID is required.",
    unknown_quest_id: "Unknown quest ID.",
    quest_not_assigned: "Quest is not assigned for today.",
    quest_already_completed: "Quest already completed.",

    // Chain rejects
    transaction_rejected: "Transaction rejected.",
    out_of_gas: "Transaction ran out of gas.",
    fee_payer_insufficient_funds: "Fee payer has insufficient funds.",
    empty_error_log: "Chain returned an empty error log for this transaction.",

    // Client-only
    not_logged_in: "You must be logged in to continue.",
    target_required: "Target is required.",
    reason_required: "Reason is required.",
    tx_hash_required: "Transaction hash is required.",
    invalid_recipient_or_amount: "Recipient or amount is invalid.",
    recipient_must_be_mirage1: "Recipient must be a mirage1 address.",
    invalid_signer_address: "Invalid signer address.",
    address_invalid: "Invalid address.",
    missing_recovery_phrase: "Recovery phrase is missing.",
    transaction_failed: "Transaction failed.",
    client_error: "Something went wrong. Please try again.",
};

/**
 * Format an API error response into user-facing copy.
 *
 * @param {object|string} resp - API response object with { error, error_code } or an error_code string.
 * @returns {string} User-friendly error message.
 */
export function formatError(resp) {
    const code = typeof resp === 'string' ? resp : resp?.error_code;
    if (!code) {
        try { console.error('[errorMessages] missing error_code', resp); } catch (_) { }
        return "Missing error code.";
    }
    const mapped = ERROR_MAP[code];
    if (!mapped) {
        try { console.error('[errorMessages] unknown error_code', code, resp); } catch (_) { }
        return `Unknown error code: ${code}.`;
    }
    return mapped;
}

/**
 * Check if an error_code matches a specific code.
 * Useful for conditional UI logic (e.g. hiding forms on specific errors).
 */
export function isErrorCode(resp, code) {
    if (!resp) return false;
    return (typeof resp === 'string' ? resp : resp.error_code) === code;
}

const errorMessages = { formatError, isErrorCode };
export default errorMessages;
