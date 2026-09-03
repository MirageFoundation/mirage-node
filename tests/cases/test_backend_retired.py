from __future__ import annotations

from tests.common import _pass, _fail, _get, _post

_RETIRED_POST_PATHS = (
    "/api/core/annotate",
    "/api/core/enable_agent",
    "/api/core/disable_agent",
    "/api/core/set_agents",
    "/api/core/create_community",
    "/api/core/set_community_metadata",
    "/api/core/transfer_community",
    "/api/rewards/claim",
    "/api/referrals/opt-in",
    "/api/validate_invite_code",
)

_TYPED_DISABLED_GET_PATHS = (
    ("/api/get_agents", {"agents": []}),
    ("/api/get_invite_codes", {"codes": [], "total": 0, "available": 0}),
    ("/api/rewards/achievements", {"achievements": []}),
    ("/api/referrals/precheck", {"valid": False, "available": 0, "error": "referrals_retired"}),
)


def test_retired_endpoints(backend: str):
    """Every endpoint dropped in v1.39.0 answers 410 and names itself."""
    for path in _RETIRED_POST_PATHS:
        label = path.rsplit("/", 1)[-1]
        code, body = _post(f"{backend}{path}", {})
        if code == 410 and (body or {}).get("retired") == label:
            _pass(f"retired.{label}")
        else:
            _fail(f"retired.{label}", f"code={code} body={body}")

    for path, expected in _TYPED_DISABLED_GET_PATHS:
        code, body = _get(f"{backend}{path}")
        label = path.strip("/").replace("/", "_")
        if code == 200 and all((body or {}).get(key) == value for key, value in expected.items()):
            _pass(f"retired.typed_disabled_{label}")
        else:
            _fail(f"retired.typed_disabled_{label}", f"code={code} body={body}")

    code, summary = _get(f"{backend}/api/rewards/summary")
    summary_payload = {key: value for key, value in (summary or {}).items() if key != "_http_status"}
    reward_keys = {
        "disabled",
        "suspended",
        "daily_quests",
        "flash_quest",
        "pending_rewards",
        "seconds_until_reset",
        "reward_multiplier",
        "total_mirage",
        "total_mirage_after_multiplier",
        "pending_invite_codes",
        "claiming_available",
        "debug",
    }
    if code == 200 and set(summary_payload) == reward_keys and summary_payload.get("disabled") is True:
        _pass("retired.typed_disabled_rewards_summary")
    else:
        _fail("retired.typed_disabled_rewards_summary", f"code={code} body={summary}")

    code, referrals = _get(f"{backend}/api/referrals/summary", {"limit": 7, "offset": 3})
    expected_referrals = {
        "referrals": [],
        "total": 0,
        "period_start": 0,
        "period_end": 0,
        "limit": 7,
        "offset": 3,
        "has_more": False,
    }
    referral_payload = {key: value for key, value in (referrals or {}).items() if key != "_http_status"}
    if code == 200 and referral_payload == expected_referrals:
        _pass("retired.typed_disabled_referrals_summary")
    else:
        _fail("retired.typed_disabled_referrals_summary", f"code={code} body={referrals}")

    code, body = _get(f"{backend}/api/get_posts", {"topic": "test"})
    if code == 200 and (body or {}).get("error_code") != "topic_retired":
        _pass("retired.get_posts_topic_param_restored")
    else:
        _fail("retired.get_posts_topic_param_restored", f"code={code} body={body}")

    code, body = _get(f"{backend}/api/get_posts", {"community": "test", "limit": 1})
    if code == 200 and (body or {}).get("error_code") != "topic_retired":
        _pass("retired.get_posts_community_param_still_works")
    else:
        _fail("retired.get_posts_community_param_still_works", f"code={code} body={body}")
