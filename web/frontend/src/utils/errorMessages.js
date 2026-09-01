/**
 * Centralized error message mapping.
 *
 * Backend returns { error: "human readable", error_code: "snake_case" }.
 * UI must display messages based on error_code only (no string fallbacks).
 */

const ERROR_MAP = {
    // Registration / signup
    registration_disabled: "Registration is currently disabled on this node.",

    // Username
    username_required: "A username is required.",
    username_too_short: "Your username is too short.",
    username_too_long: "Your username is too long.",
    username_invalid_format: "Usernames can only contain letters, numbers, and hyphens, and must start with a letter or number.",
    username_taken: "That username is already taken.",

    // Auth / envelope
    missing_fields: "Missing required fields.",
    invalid_pubkey: "Invalid public key.",
    invalid_signature: "Invalid signature.",
    invalid_timestamp: "Invalid timestamp.",
    timestamp_required: "Timestamp is required.",
    timestamp_must_be_millis: "Timestamp must be in milliseconds.",
    timestamp_outside_window: "Timestamp is outside the allowed window.",
    envelope_expired: "This request took too long to reach the chain. Please try again.",
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
    visitor_id_required: "Visitor id is required.",
    control_characters: "Fields contain invalid control characters.",
    forbidden: "You do not have permission to perform this action.",
    unauthorized: "Unauthorized.",
    signature_required: "A signed request is required.",
    // Node-to-node: a person only reaches this by calling the endpoint by hand.
    invalid_identity_challenge: "An identity challenge needs an origin and a nonce.",
    not_found: "Not found.",

    // Server state
    node_catching_up: "The node is syncing. Please try again shortly.",
    backend_not_initialized: "The server is starting up. Please try again shortly.",
    indexer_unavailable: "Data service is temporarily unavailable.",
    internal_error: "Something went wrong. Please try again.",
    debug_localhost_only: "Debug endpoints are only available on localhost.",
    upgrade_required: "This app version is out of date. Please refresh or update.",
    gone: "That feature is no longer available.",

    // Request shape
    invalid_input: "That request wasn't valid. Please try again.",
    invalid_input_type: "That request wasn't valid. Please try again.",
    invalid_base64: "That request wasn't valid. Please try again.",
    invalid_limit: "That request wasn't valid. Please try again.",
    invalid_offset: "That request wasn't valid. Please try again.",
    invalid_cursor: "That request wasn't valid. Please try again.",
    missing_author: "An author is required.",

    // PoW
    insufficient_pow_precheck: "Proof-of-work is insufficient. Please try again.",
    invalid_pow_difficulty: "Invalid proof-of-work difficulty.",
    invalid_pow: "Invalid proof-of-work value.",
    pow_not_allowed_for_award: "Proof-of-work is not allowed for awards.",
    pow_not_allowed_for_set_auto_renewal: "Proof-of-work is not allowed for auto-renewal.",
    pow_required: "Proof-of-work is required.",
    invalid_pow_fields: "Invalid proof-of-work fields.",
    invalid_last_block_hash: "Invalid last block hash.",
    pow_timeout: "Proof-of-work took too long. Please try again later.",
    pow_worker_failed: "Proof-of-work failed. Please try again.",
    pow_worker_invalid_response: "Proof-of-work failed due to an invalid worker response.",
    pow_wasm_csp_blocked: "This browser blocked the proof-of-work engine. Please try again, or use a different browser.",

    // Content / posts
    title_too_long: "Your title exceeds the maximum length.",
    content_too_long: "Your post exceeds the maximum length.",
    community_too_short: "Community name is too short.",
    community_too_long: "Community name is too long.",
    community_invalid_format: "Community name contains invalid characters.",
    community_too_many_wildcards: "Too many * wildcards in that community pattern.",
    post_community_required: "A community is required for new posts.",
    comment_content_required: "Comment text is required.",
    comment_not_found: "Comment not found.",
    post_not_found: "Post not found.",
    invalid_target: "Invalid target.",
    invalid_target_format: "Invalid target format.",
    target_not_found: "The target post or comment was not found.",
    target_mismatch: "Cannot change the parent of an existing post.",
    comment_must_not_include_community: "Comments must not include a community.",
    tag_too_long: "Tag is too long.",
    invalid_tag: "Invalid tag.",
    invalid_override: "Invalid override.",
    post_id_required: "Post ID is required.",
    comment_id_required: "Comment ID is required.",
    invalid_hash: "Invalid or missing hash.",
    target_must_be_mirage1: "Target must be a valid mirage1 address.",

    // Communities / curation
    community_required: "A community is required.",
    community_invalid: "That community name isn't valid.",
    target_and_community_required: "Both a target and a community are required.",
    community_and_name_required: "A community and a name are required.",
    invalid_curation_mode: "Invalid curation mode.",
    invalid_curated: "Invalid curated filter.",
    curation_team_not_found: "That curator team no longer exists.",
    missing_viewer: "Sign in to load this view.",
    invalid_pinned_team_id: "Invalid pinned team.",
    epoch_ids_required: "At least one epoch is required.",
    too_many_epoch_ids: "You can claim at most 30 epochs at a time.",
    epoch_ids_not_increasing: "Epochs must be listed in increasing order.",
    topic_retired: "This page still used an outdated community link. Refresh to load the community instead.",
    curation_action_pending: "That curator action is already pending.",

    // Media
    media_not_list: "Media must be provided as a list.",
    posts_not_list: "Posts must be provided as a list.",
    media_limit_exceeded: "Too many media attachments.",
    media_item_too_long: "A media URL is too long.",
    media_must_use_https: "Media URLs must use HTTPS.",
    media_control_characters: "Media contains invalid control characters.",

    // Uploads
    uploads_disabled: "Uploads are disabled on this node.",
    media_file_required: "Please choose a file to upload.",
    media_invalid_kind: "Uploads must be an image or a video.",
    media_invalid_type: "That file type is not supported.",
    media_too_large: "That file is too large.",
    media_metadata_required: "Video duration and height are required.",
    video_too_long: "That video is too long.",
    video_resolution_too_high: "That video's resolution is too high for its length on this node.",
    media_store_failed: "The upload service failed. Please try again.",
    media_provider_not_configured: "Uploads are not configured on this node.",
    media_unknown_provider: "This node has an unknown upload provider configured.",
    media_edge_unauthorized: "Upload registration was rejected.",

    // Biography
    biography_too_long: "Your biography exceeds the maximum length.",

    // Blocks / follows
    cannot_block_self: "You cannot block yourself.",
    cannot_follow_self: "You cannot follow yourself.",
    post_already_blocked: "You already blocked this post.",
    user_already_blocked: "You already blocked this user.",
    community_already_blocked: "You already blocked this community.",
    user_already_followed: "You already follow this user.",
    community_already_joined: "You already joined this community.",
    user_must_be_mirage1: "User must be a valid mirage1 address.",
    block_post_in_progress: "Block post request already in progress.",
    unblock_post_in_progress: "Unblock post request already in progress.",
    block_user_in_progress: "Block user request already in progress.",
    unblock_user_in_progress: "Unblock user request already in progress.",
    block_community_in_progress: "Block community request already in progress.",
    unblock_community_in_progress: "Unblock community request already in progress.",
    follow_user_in_progress: "Follow user request already in progress.",
    unfollow_user_in_progress: "Unfollow user request already in progress.",
    join_community_in_progress: "Join community request already in progress.",
    leave_community_in_progress: "Leave community request already in progress.",
    vote_already_pending: "Vote already pending.",
    delete_in_progress: "Delete account request already in progress.",

    missing_tier_config: "Subscription tier configuration is missing.",
    missing_profile_level: "Profile level is missing.",

    // Subscription
    not_subscriber: "This action requires an active subscription or an admin account.",
    already_curator: "You already curate a team in this community.",
    leave_blocked_by_curation: "You curate a team here. Leave the curator team first, then you can leave the community.",
    not_joined: "You are not a member of this community.",
    invalid_level: "Invalid subscription level.",
    invalid_period_count: "Choose between 1 and 12 subscription periods.",
    insufficient_balance: "Insufficient balance to complete this transaction.",
    admin_insufficient_balance: "Your account balance is too low to cover the transaction fee.",
    insufficient_funds: "Node does not have enough gas for this transaction.",
    auto_renew_required: "Auto-renewal setting is required.",
    gift_invalid_target: "The gift recipient must be a valid mirage1 address.",
    gift_rejected_higher_tier: "That user already has a higher tier than the one you are gifting.",

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

    // Reports / moderation
    reason_too_long: "Report reason is too long (max 200 characters).",
    admin_required: "Admin address is required.",
    owner_required: "Owner is required.",

    // Search / query
    query_required: "Query parameter is required.",
    count_must_be_non_negative: "Count must be non-negative.",
    invalid_amount: "Invalid amount.",
    amount_must_be_positive: "Amount must be positive.",
    amount_too_small: "Amount is below the minimum.",
    invalid_month_format: "Invalid month format (use YYYY-MM).",
    invalid_max_depth: "Invalid max depth.",
    unsupported_sort_mode: "Unsupported sort mode.",

    // Upload
    upload_service_error: "Upload service encountered an error.",
    cloudflare_not_configured: "Upload service is not configured.",
    cloudflare_stream_not_configured: "Stream upload service is not configured.",
    cloudflare_no_url: "Upload service did not return a URL.",
    cloudflare_stream_no_url: "Stream upload service did not return a URL.",
    image_type_only: "Only image uploads are supported.",
    invalid_video_uid: "Invalid video UID.",
    not_configured: "Service is not configured.",
    retry: "Please retry the request.",
    stats_event_disabled: "Stats events are disabled on this node.",
    invalid_user_level: "Invalid user level.",

    // Quests

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
    missing_onboarding_handoff: "Recovery phrase is missing.",
    handoff_owner_mismatch: "Session changed while submitting. Please try again.",
    missing_entry_owner: "Session changed while submitting. Please try again.",
    transaction_failed: "Transaction failed.",
    client_error: "Something went wrong. Please try again.",
    tx_cancelled: "Transaction was cancelled. Please try again.",
    owner_mismatch: "Session changed while submitting. Please try again.",
    pipeline_failure: "Transaction failed. Please try again.",
    missing_seed: "Recovery phrase is missing.",
    'missing onboarding handoff seed': "Recovery phrase is missing.",
    'handoff owner mismatch': "Session changed while submitting. Please try again.",
    'missing recovery phrase': "Recovery phrase is missing.",
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
        // Cancelled queue drains use { cancelled, reason } without error_code.
        const reason = typeof resp === 'object' && resp ? (resp.reason || resp.details || resp.error) : null;
        if (reason) {
            const mappedReason = ERROR_MAP[reason];
            if (mappedReason) return mappedReason;
            try { console.error('[errorMessages] cancelled/unmapped without error_code', resp); } catch (_) { }
            return String(reason);
        }
        // Client/network throws (TypeError, Error from fetch) carry .message only.
        if (resp instanceof Error && resp.message) {
            try { console.error('[errorMessages] client error without error_code', resp); } catch (_) { }
            return resp.message;
        }
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
