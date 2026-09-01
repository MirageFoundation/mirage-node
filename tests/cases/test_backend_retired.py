from __future__ import annotations

from tests.common import _pass, _fail, _get, _post

# Paths retired in v1.39.0. They keep their pre-rename spelling on purpose: an
# outdated client sends `follow_topic` and `get_topics` verbatim, so those are
# the strings the 410 gate has to answer for. `web/backend/factory.py` rejects
# them in a before_request hook, ahead of routing, so a stub handler in routes/
# would be unreachable — the gate is the whole implementation.
_RETIRED_POST_PATHS = (
    "/api/core/annotate",
    "/api/core/enable_agent",
    "/api/core/disable_agent",
    "/api/core/set_agents",
    "/api/core/follow_topic",
    "/api/core/unfollow_topic",
    "/api/core/block_topic",
    "/api/core/unblock_topic",
    "/api/core/create_community",
    "/api/core/set_community_metadata",
    "/api/core/transfer_community",
)

_RETIRED_GET_PATHS = (
    "/api/get_agents",
    "/api/get_topics",
    "/api/search_topics",
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

    for path in _RETIRED_GET_PATHS:
        label = path.rsplit("/", 1)[-1]
        code, body = _get(f"{backend}{path}")
        if code == 410 and (body or {}).get("retired") == label:
            _pass(f"retired.{label}")
        else:
            _fail(f"retired.{label}", f"code={code} body={body}")

    # get_posts survived the rename but its `topic=` param did not. Both halves
    # are asserted because the guard was twice written against `community=`
    # instead, which rejects every real caller and takes the whole feed down.
    code, body = _get(f"{backend}/api/get_posts", {"topic": "test"})
    if (body or {}).get("error_code") == "topic_retired":
        _pass("retired.get_posts_topic_param")
    else:
        _fail("retired.get_posts_topic_param", f"code={code} body={body}")

    code, body = _get(f"{backend}/api/get_posts", {"community": "test", "limit": 1})
    if code == 200 and (body or {}).get("error_code") != "topic_retired":
        _pass("retired.get_posts_community_param_still_works")
    else:
        _fail("retired.get_posts_community_param_still_works", f"code={code} body={body}")
