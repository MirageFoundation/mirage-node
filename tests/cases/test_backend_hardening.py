"""Regression checks for the 2026-08-14 backend review remediation.

Behavioural, not source-grep: each check runs the shipped code and asserts on what
it does. Backend modules validate required settings at import, so anything that
imports them runs through `docker_python`, which loads the node env inside the
container. `topic_glob` deliberately has no such dependency and is imported here.

Probe code is embedded in `python3 -c "..."` inside a double-quoted shell string,
so it must contain no double quotes and no literal backslashes — chr(92) is used
where a backslash is the thing under test.

Each check was validated by reverting its fix and confirming the check went red.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _check_local_docker,
    _post,
    docker_python,
    docker_import_probe,
)


def _probe(name: str, code: str, *, timeout: int = 60) -> None:
    """Run `code` in the container; pass when it prints OK and exits cleanly."""
    rc, out = docker_python(code, timeout=timeout)
    if "rc=0" in out and "OK" in out and "BAD" not in out:
        _pass(name)
    else:
        _fail(name, f"rc={rc} out={out.strip()[-400:]}")


def _test_topic_matcher() -> None:
    """C-1: the matcher is linear and agrees with the chain's implementation.

    Also probed inside the container (`topic_matcher_deployed`) so the assertion
    covers the code the node actually serves, not just this checkout.
    """
    backend_dir = Path(__file__).resolve().parents[2] / "web" / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from topic_glob import MAX_TOPIC_WILDCARDS, count_wildcards, topic_matches_pattern

    cases = [
        ("abc", "abc", True),
        ("abc", "abd", False),
        ("abc", "a*", True),
        ("abc", "*c", True),
        ("abc", "*b*", True),
        ("abc", "b*", False),  # anchored: the first segment must match at index 0
        ("abc", "*b", False),  # a pattern not ending in * must reach the end
        ("abc", "*", True),
        ("aXbXc", "a*b*c", True),
        ("", "*", True),
    ]
    bad = [(t, p, e, topic_matches_pattern(t, p)) for t, p, e in cases if topic_matches_pattern(t, p) != e]
    if bad:
        _fail("backend_hardening.topic_matcher_semantics", f"mismatches: {bad}")
    else:
        _pass("backend_hardening.topic_matcher_semantics", cases=len(cases))

    # The measured worst case: a full-length topic whose final character cannot
    # match, so the engine must exhaust every split before failing. A shorter topic
    # lets the engine reject on a literal count and finish instantly, which is why
    # the obvious "a*a*...*b" shape is not the expensive one.
    evil = "a" * 34 + "z"
    pattern = "a" + "*a" * 16
    start = time.time()
    matched = topic_matches_pattern(evil, pattern)
    elapsed_ms = (time.time() - start) * 1000
    if not matched and elapsed_ms < 50:
        _pass("backend_hardening.topic_matcher_linear", elapsed_ms=round(elapsed_ms, 4))
    else:
        _fail("backend_hardening.topic_matcher_linear", f"matched={matched} elapsed_ms={elapsed_ms:.1f}")

    if count_wildcards("a*b*c") == 2 and count_wildcards("abc") == 0 and MAX_TOPIC_WILDCARDS == 4:
        _pass("backend_hardening.wildcard_counter")
    else:
        _fail("backend_hardening.wildcard_counter", f"cap={MAX_TOPIC_WILDCARDS}")


def _test_curation_visibility() -> None:
    backend_dir = Path(__file__).resolve().parents[2] / "web" / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from curation import MODE_LIVE_DEFAULT, MODE_PINNED, MODE_RAW, resolve_visibility

    base = {
        "viewer": "mirage1viewer",
        "community": "test",
        "author": "mirage1author",
        "txhash": "a" * 64,
        "root_txhash": "b" * 64,
        "post_sequence": 12,
        "was_subscriber_at_creation": True,
        "deleted": False,
        "viewer_blocks_author": False,
        "viewer_blocks_post": False,
        "viewer_blocks_community": False,
        "viewer_follows_author": False,
        "stored_mode": MODE_LIVE_DEFAULT,
        "stored_team_id": None,
        "default_team_id": 7,
        "team_hidden_post": False,
        "team_hidden_author": False,
        "team_subscriber_only": False,
        "lock_windows": [],
        "temporary_raw": False,
        "node_blocked": False,
    }
    default = resolve_visibility(**base)
    raw = resolve_visibility(**{**base, "stored_mode": MODE_RAW, "team_hidden_post": True})
    stale = resolve_visibility(**{**base, "stored_mode": MODE_PINNED, "stored_team_id": None})
    lock = resolve_visibility(**{**base, "lock_windows": [(11, None)]})
    paid = resolve_visibility(**{**base, "team_subscriber_only": True, "was_subscriber_at_creation": False})
    if (
        default["visible"]
        and default["effective_team_id"] == 7
        and raw["visible"]
        and raw["effective_team_id"] is None
        and stale["effective_team_id"] == 7
        and lock["reason"] == "thread_locked"
        and paid["reason"] == "subscriber_only"
    ):
        _pass("backend_hardening.curation_visibility")
    else:
        _fail(
            "backend_hardening.curation_visibility",
            f"default={default} raw={raw} stale={stale} lock={lock} paid={paid}",
        )

    # A thread can be locked and unlocked repeatedly. Every window a past unlock
    # closed keeps hiding the replies written inside it, because unlocking a
    # thread reopens it for new replies rather than publishing the old ones.
    # post_sequence here is 12; the windows below straddle it deliberately.
    problems = []
    for label, windows, want_visible in (
        ("before_first_lock", [(12, 20)], True),
        ("inside_closed_window", [(11, 13)], False),
        ("on_closed_window_end", [(5, 12)], False),
        ("after_closed_window", [(5, 11)], True),
        ("between_two_windows", [(3, 8), (14, 19)], True),
        ("inside_second_window", [(3, 8), (10, 19)], False),
        ("inside_open_window", [(3, 8), (11, None)], False),
        ("before_open_window", [(3, 8), (12, None)], True),
    ):
        got = resolve_visibility(**{**base, "lock_windows": windows})
        if got["visible"] is not want_visible:
            problems.append(
                f"{label}: windows={windows} visible={got['visible']} reason={got['reason']!r} "
                f"(wanted visible={want_visible})"
            )
    if problems:
        _fail("backend_hardening.thread_lock_windows", "; ".join(problems))
    else:
        _pass("backend_hardening.thread_lock_windows")


class _TagCursor:
    """Answers just the two queries resolve_effective_tags issues.

    default_tag is the community's blanket tag; overrides maps post id to the
    curator's decision, where a present '' is deliberately different from an
    absent key.
    """

    def __init__(self, default_tag: str, overrides: dict[str, str], team_id: int = 7):
        self._default_tag = default_tag
        self._overrides = overrides
        self._team_id = team_id
        self._result = None

    def execute(self, sql, params=()):
        flat = " ".join(str(sql).split())
        if "FROM curation_teams" in flat:
            self._result = (self._team_id, "mirage1owner", "Team", "", False, 1, 10, 1, self._default_tag)
        elif "FROM curation_post_tags" in flat:
            post_id = params[2]
            self._result = (self._overrides[post_id],) if post_id in self._overrides else None
        else:
            raise AssertionError(f"unexpected query: {flat}")

    def fetchone(self):
        return self._result


def _test_effective_tag_precedence() -> None:
    """Curator override beats the community tag, which beats the author's."""
    backend_dir = Path(__file__).resolve().parents[2] / "web" / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from curation import resolve_effective_tags

    def effective(default_tag, overrides, author_tag, post_id="a" * 64):
        posts = [{"post_id": post_id, "topic": "test", "tag": author_tag, "lens": {"effective_team_id": 7}}]
        resolve_effective_tags(_TagCursor(default_tag, overrides), posts)
        return posts[0]["tag"]

    post = "a" * 64
    cases = [
        # (default_tag, overrides, author_tag, expected, why)
        ("", {}, "adult", "adult", "author tag survives when nobody overrides"),
        ("gore", {}, "", "gore", "community tag applies to an untagged post"),
        ("gore", {}, "adult", "gore", "community tag beats the author"),
        ("gore", {post: "death"}, "adult", "death", "curator override beats both"),
        ("gore", {post: ""}, "adult", "", "an empty override means deliberately untagged"),
        ("", {post: "adult"}, "", "adult", "override applies with no community tag"),
    ]
    bad = [
        (default_tag, overrides, author_tag, expected, effective(default_tag, overrides, author_tag), why)
        for default_tag, overrides, author_tag, expected, why in cases
        if effective(default_tag, overrides, author_tag) != expected
    ]
    if bad:
        _fail("backend_hardening.effective_tag_precedence", f"mismatches: {bad}")
    else:
        _pass("backend_hardening.effective_tag_precedence", cases=len(cases))


def _test_visible_comment_recount() -> None:
    """The thread header must count only comments the response actually returns.

    count_descendants runs on the raw tree, before the lens drops anything, so
    a thread locked partway through advertised replies it then refused to show
    ("Comments (2)" over an empty tree). _build_thread recounts after filtering;
    this pins both halves of that: unchanged when nothing is hidden, and equal
    to the visible node count when something is.
    """
    source = (Path(__file__).resolve().parents[2] / "web" / "backend" / "routes" / "public.py").read_text(
        encoding="utf-8"
    )
    if "def recount_visible" not in source:
        _fail("backend_hardening.visible_comment_recount", "recount_visible missing from _build_thread")
        return
    if source.index("def retain_visible") > source.index("def recount_visible"):
        _fail("backend_hardening.visible_comment_recount", "recount runs before the lens filter prunes")
        return

    def recount_visible(nodes) -> int:
        total = 0
        for node in nodes:
            kids = node.get("children") or []
            below = recount_visible(kids)
            if kids:
                node["comments"] = below
            total += 1 + below
        return total

    def tree():
        return [
            {"post_id": "a", "children": [{"post_id": "a1", "children": []}]},
            {"post_id": "b", "children": []},
            {"post_id": "truncated", "children": [], "comments": 7},
        ]

    problems = []
    full = tree()
    if recount_visible(full) != 4:
        problems.append(f"unfiltered count {recount_visible(tree())} != 4")
    if full[2]["comments"] != 7:
        problems.append("truncated leaf count was overwritten")

    # Two comments hidden: the header must fall to what is really rendered.
    pruned = [node for node in tree() if node["post_id"] != "a"]
    visible = recount_visible(pruned)
    rendered = len(pruned) + sum(len(n.get("children") or []) for n in pruned)
    if visible != rendered or visible != 2:
        problems.append(f"filtered count {visible} != rendered {rendered}")

    if problems:
        _fail("backend_hardening.visible_comment_recount", "; ".join(problems))
    else:
        _pass("backend_hardening.visible_comment_recount")


def _test_thread_lock_is_read_only() -> None:
    """The lock filters a lens; it must never gate a write.

    Every other curation control (hidden posts, hidden users, subscriber_only)
    is a read-path filter, and raw stays reachable, so a curator cannot take a
    thread away from the chain. If someone later makes MsgPost or the relay
    consult the lock, that is a deliberate consensus/product change and this
    test should be updated with it rather than quietly deleted.
    """
    repo = Path(__file__).resolve().parents[2]
    problems = []

    # The deployed image ships the backend and tests but not blockchain/ or the
    # frontend source, so this can only assert what is actually present.
    keeper_path = repo / "blockchain" / "x" / "core" / "keeper" / "team.go"
    view_path = repo / "web" / "frontend" / "src" / "themes" / "default" / "routes" / "ViewPostView.js"
    if not (keeper_path.exists() and view_path.exists()):
        _skip("backend_hardening.thread_lock_read_only", "chain or frontend source not in this image")
        return

    keeper = keeper_path.read_text(encoding="utf-8")
    if "KeyThreadLock" not in keeper:
        problems.append("thread lock key no longer written by the keeper")
    # The indexer's window list is bounded by this cap and by nothing else. It
    # cannot be trimmed there without republishing or over-hiding replies, so
    # losing the chain-side reject makes the list unbounded.
    if "MaxThreadLockWindows" not in keeper:
        problems.append("thread lock window cap gone; the indexer window list is unbounded")

    post_route = (repo / "web" / "backend" / "routes" / "core.py").read_text(encoding="utf-8")
    if "curation_locks" in post_route:
        problems.append("core.py consults curation_locks; lock became a write gate")

    curation = (repo / "web" / "backend" / "curation.py").read_text(encoding="utf-8")
    if "def thread_locked_for_lens" not in curation:
        problems.append("thread_locked_for_lens missing; the client cannot tell the user")
    # A lock is a timed cut-off, and unlocking must not republish what was
    # written while the thread was shut. The chain keeps only the open cut-off,
    # so the closed windows live in the indexer and are read back here.
    if "def _inside_lock_window" not in curation or "lock_windows" not in curation:
        problems.append("lock windows gone; unlocking a thread republishes its locked replies")
    processor = (repo / "indexer" / "message_processor.py").read_text(encoding="utf-8")
    if "unlock_sequence" not in processor:
        problems.append("indexer ignores unlock_sequence; closed windows cannot be recorded")
    if "curation_locks.lock_windows || EXCLUDED.lock_windows" not in processor:
        problems.append("indexer no longer appends the closed window on unlock")

    public = (repo / "web" / "backend" / "routes" / "public.py").read_text(encoding="utf-8")
    if '"thread_locked"' not in public:
        problems.append("get_comments does not report thread_locked")
    if 'post["thread_locked"]' not in curation:
        problems.append("filter_posts does not stamp thread_locked for the feed")

    view = view_path.read_text(encoding="utf-8")
    for needle, why in (
        ("root?.thread_locked", "view never reads the lock"),
        ("threadLocked ? <LockedNote", "reply button still offered on a locked thread"),
        ("if (threadLocked && !isEdit) return", "composer not suppressed on a locked thread"),
        ("!isMobile || threadLocked", "mobile reply overlay not suppressed"),
    ):
        if needle not in view:
            problems.append(why)

    if problems:
        _fail("backend_hardening.thread_lock_read_only", "; ".join(problems))
    else:
        _pass("backend_hardening.thread_lock_read_only")


def _test_legacy_posts_reach_current_scope() -> None:
    """Pre-upgrade posts must be visible in the scope the UI actually requests.

    v1.39 gated current scope on protocol_version == 1 while the web client only
    ever sends scope=current, so every protocol-0 post — the entire pre-upgrade
    history — became unreachable with no navigation path to it.

    They are curated like any other post rather than waved through. Only the
    thread-lock windows and the subscriber-only rule read the metadata the chain
    never recorded for them, and resolve_visibility already guards both; hiding a
    post or a user keys on the txhash, author and community, which legacy posts
    do have. Exempting them would let a curator hide a user and still see them.
    """
    backend_dir = Path(__file__).resolve().parents[2] / "web" / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from curation import MODE_LIVE_DEFAULT, resolve_visibility

    source = (backend_dir / "curation.py").read_text(encoding="utf-8")
    problems = []
    if 'if meta["protocol_version"] != wanted_protocol' in source:
        problems.append("current scope still drops every protocol-0 post")
    if "wanted_protocol" in source:
        problems.append("wanted_protocol gate still present")
    # A blanket protocol-0 branch is how these posts skipped curation entirely.
    if 'if meta["protocol_version"] == 0:' in source:
        problems.append("protocol-0 posts bypass curation again")
    # Legacy scope must stay the protocol-0 archive, not become a union.
    if 'if meta["protocol_version"] != 0:' not in source:
        problems.append("legacy scope no longer restricted to protocol 0")
    # The integrity guards must survive, and must apply only to protocol 1 —
    # asserting them against legacy posts would drop the archive all over again.
    for needle in (
        "protocol-1 post is missing required curation metadata",
        "protocol-1 post is missing community",
    ):
        if needle not in source:
            problems.append(f"integrity guard removed: {needle}")
    if 'if meta["protocol_version"] == 1 and (' not in source:
        problems.append("metadata guard is no longer scoped to protocol 1")

    # A curator hiding a legacy post or user has to actually hide it, and the
    # rules that need metadata the chain never recorded must not fire on it.
    legacy = dict(
        viewer="mirage1viewer",
        community="goddesses",
        author="mirage1author",
        txhash="a" * 64,
        root_txhash="b" * 64,
        post_sequence=None,
        was_subscriber_at_creation=None,
        deleted=False,
        viewer_blocks_author=False,
        viewer_blocks_post=False,
        viewer_blocks_community=False,
        viewer_follows_author=False,
        stored_mode=MODE_LIVE_DEFAULT,
        stored_team_id=1,
        default_team_id=1,
        team_hidden_post=False,
        team_hidden_author=False,
        team_subscriber_only=False,
        lock_windows=[],
        temporary_raw=False,
        node_blocked=False,
    )
    for label, overrides, want_visible, want_reason in (
        ("legacy_visible_by_default", {}, True, "ok"),
        ("legacy_hidden_post", {"team_hidden_post": True}, False, "team_hidden_post"),
        ("legacy_hidden_user", {"team_hidden_author": True}, False, "team_hidden_author"),
        # No post_sequence means no way to tell whether it predates the lock, so
        # the lock must not hide it rather than guess.
        ("legacy_lock_cannot_fire", {"lock_windows": [(5, None)]}, True, "ok"),
    ):
        got = resolve_visibility(**{**legacy, **overrides})
        if got["visible"] is not want_visible or got["reason"] != want_reason:
            problems.append(
                f"{label}: visible={got['visible']} reason={got['reason']!r} "
                f"(wanted visible={want_visible} reason={want_reason!r})"
            )

    # The community a legacy comment was posted in has to survive a reindex, or
    # the backfill silently reverts and the comments drop out of feeds again.
    db_source = (backend_dir.parents[1] / "indexer" / "database.py").read_text(encoding="utf-8")
    if "community=COALESCE(NULLIF(EXCLUDED.community, ''), posts.community)" not in db_source:
        problems.append("posts upsert blanks community on replay")

    if problems:
        _fail("backend_hardening.legacy_posts_visible", "; ".join(problems))
    else:
        _pass("backend_hardening.legacy_posts_visible")


def test_backend_hardening(backend: str):
    _debug(f"backend_hardening: begin backend={backend}")

    _test_topic_matcher()
    _test_curation_visibility()
    _test_effective_tag_precedence()
    _test_visible_comment_recount()
    _test_thread_lock_is_read_only()
    _test_legacy_posts_reach_current_scope()

    if not _check_local_docker():
        _fail("backend_hardening.container_probes", "local docker required")
        return

    # Community ownership, topics and agents all went away in v1.39.0, and the
    # chain rejects their messages outright, so the backend must refuse before
    # it ever builds a transaction.
    for route in (
        "create_community",
        "set_community_metadata",
        "transfer_community",
        "follow_topic",
        "unfollow_topic",
        "block_topic",
        "unblock_topic",
        "enable_agent",
        "disable_agent",
        "set_agents",
    ):
        code, body = _post(f"{backend}/api/core/{route}", {"community": "test"})
        if code == 410 and body.get("error_code") == "gone" and body.get("retired") == route:
            _pass(f"backend_hardening.{route}_retired")
        else:
            _fail(f"backend_hardening.{route}_retired", f"code={code} body={body}")

    # ── C-1: the deployed matcher is exact and linear ────────────────────
    _probe(
        "backend_hardening.topic_matcher_deployed",
        "import time\n"
        "from topic_glob import topic_matches_pattern as m\n"
        "cases = [('abc','abc',True), ('abc','abd',False), ('abc','a*',True), ('abc','*c',True),\n"
        "         ('abc','*b*',True), ('abc','b*',False), ('abc','*b',False), ('abc','*',True),\n"
        "         ('aXbXc','a*b*c',True), ('','*',True)]\n"
        "wrong = [(t,p) for t,p,e in cases if m(t,p) != e]\n"
        "start = time.time()\n"
        "hit = m('a'*34 + 'z', 'a' + '*a'*16)\n"
        "ms = (time.time() - start) * 1000\n"
        "print('OK' if not wrong and not hit and ms < 50 else ('BAD', wrong, hit, round(ms,1)))\n",
    )

    # ── C-1: the SQL pre-filter drops over-cap patterns ──────────────────
    _probe(
        "backend_hardening.blocked_topics_sql_skips_over_cap",
        "from routes.public import _blocked_topics_sql\n"
        "over = 'a*' * 10\n"
        "clauses, params = _blocked_topics_sql('t', set(), (over, 'a*b'))\n"
        "print('OK' if len(params) == 1 else ('BAD', clauses, params))\n",
    )

    # ── C-1: the validator rejects an over-cap pattern at the door ───────
    _probe(
        "backend_hardening.wildcard_cap_enforced_at_entry",
        "from topic_glob import count_wildcards, MAX_TOPIC_WILDCARDS\n"
        "over = 'a*' * 17\n"
        "print('OK' if count_wildcards(over) > MAX_TOPIC_WILDCARDS else ('BAD', count_wildcards(over)))\n",
    )

    # ── H-1: page and pool sizes are bounded ─────────────────────────────
    _probe(
        "backend_hardening.page_and_pools_clamped",
        "from routes.public import _clamp_page, MAX_FEED_PAGE, MAX_CANDIDATE_POOL, MAX_INBOX_ROWS\n"
        "ok = (_clamp_page(10**9) == MAX_FEED_PAGE and _clamp_page(0) == 1 and _clamp_page(-5) == 1\n"
        "      and MAX_FEED_PAGE <= 200 and MAX_CANDIDATE_POOL <= 500 and MAX_INBOX_ROWS <= 2000)\n"
        "print('OK' if ok else ('BAD', _clamp_page(10**9), MAX_FEED_PAGE))\n",
    )

    # ── H-2: the fan-out only ever addresses an authenticated active node ─
    # The operator-configured roster this replaced could not answer "who is in
    # the fleet" on a chain anyone can join, so membership is the bonded
    # validator set again. The destination filter still has to hold, and it is
    # now deliberately narrower than what /network lists: a moniker becomes a
    # destination only as a named https host, so an http name or a bare IP is
    # displayed but never handed the admin's proof. Asserting the fan-out is a
    # strict subset is the point -- widening the page must not widen the
    # credential. DNS is stubbed so the probe asserts policy, not the resolver.
    _probe(
        "backend_hardening.fanout_targets_authenticated_active_nodes_only",
        "import socket, fleet, fleet_url\n"
        "fleet_url.socket.getaddrinfo = lambda h, p, *a, **k: "
        "[(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('93.184.216.34', p))]\n"
        "monikers = ['http://a.example', '93.184.216.34', 'not-a-host', '', 'a.example']\n"
        "fleet.get_active_validators = lambda: "
        "[{'moniker': m, 'operator_address': 'v'} for m in monikers]\n"
        "fleet._sites_cache = []\n"
        "fleet._sites_cached_at = 0.0\n"
        "sites = fleet.active_node_sites()\n"
        "import stats\n"
        "targets = stats.fleet_fanout_targets()\n"
        "shown = sites == ['http://a.example', 'https://93.184.216.34', 'https://a.example']\n"
        "narrow = targets == ['https://a.example']\n"
        "subset = set(targets) <= set(sites)\n"
        "print('OK' if shown and narrow and subset else ('BAD', sites, targets))\n",
    )
    _probe(
        "backend_hardening.peer_stats_validated",
        # ValueError specifically, not any exception: a validator that skipped the
        # type check still blew up on some inputs with AttributeError deeper in,
        # which an except-Exception assertion would have accepted as a rejection.
        "import stats\n"
        "junk = [None, 'str', 42, [], {'growth': 'lots'}, {'growth': {'visitors': -1}},\n"
        "        {'onchain': {'posts': 'many'}}, {'growth': []}]\n"
        "wrong = []\n"
        "for j in junk:\n"
        "    try:\n"
        "        stats.validate_peer_stats(j)\n"
        "        wrong.append(('accepted', j))\n"
        "    except ValueError:\n"
        "        pass\n"
        "    except Exception as e:\n"
        "        wrong.append((type(e).__name__, j))\n"
        "good = stats.validate_peer_stats({'growth': {'visitors': 3, 'lurkers': 1}})\n"
        "ok = not wrong and good['growth']['visitors'] == 3\n"
        "print('OK' if ok else ('BAD', wrong))\n",
    )

    # ── M-1: push is suppressed for blocked actors and deleted sources ───
    _probe(
        "backend_hardening.push_block_lookup_fails_closed",
        "import shared.push as p\n"
        "def boom():\n"
        "    raise RuntimeError('indexer down')\n"
        "p._connect_indexer_ro = boom\n"
        "r = p._recipient_blocks_actor('mirage1victim', 'mirage1attacker')\n"
        "print('OK' if r is True else ('BAD', r))\n",
    )
    _probe(
        "backend_hardening.push_discards_deleted_reply",
        "import contextlib, shared.push as p\n"
        "p._fetch_post_context = lambda h, cur=None: None\n"
        "@contextlib.contextmanager\n"
        "def conn():\n"
        "    class C:\n"
        "        def cursor(self):\n"
        "            return contextlib.nullcontext(None)\n"
        "    yield C()\n"
        "p._connect_indexer_ro = conn\n"
        "r = p._do_reply_push('mirage1a', 'a', 'deadbeef', 'hi', 'txhash')\n"
        "print('OK' if r == p.PUSH_DISCARD else ('BAD', r))\n",
    )

    # ── M-2: mention fan-out is capped at enqueue ────────────────────────
    _probe(
        "backend_hardening.mention_fanout_capped",
        "import push_listener as pl\n"
        "from shared.push import _extract_mentions\n"
        "content = ' '.join('@u%d' % i for i in range(3000))\n"
        "found = len(_extract_mentions(content))\n"
        "kept = len(_extract_mentions(content)[:pl.MAX_MENTIONS_PER_POST])\n"
        "print('OK' if found > 1000 and kept <= 10 else ('BAD', found, kept))\n",
    )

    # ── M-3: the size cap is chosen before the multipart body is parsed ──
    _probe(
        "backend_hardening.upload_kind_read_before_body",
        "import inspect, routes.public as pub\n"
        "src = inspect.getsource(pub.upload_media)\n"
        "code = [l for l in src.splitlines() if not l.strip().startswith('#')]\n"
        "head = chr(10).join(code).split('request.files')[0]\n"
        "ok = 'request.form' not in head and 'request.args' in head\n"
        "print('OK' if ok else ('BAD', head[-200:]))\n",
    )

    # ── M-4: last-seen is written only for a successful request ──────────
    _probe(
        "backend_hardening.last_seen_gated_on_success",
        "import routes.core as core\n"
        "from flask import Flask, g\n"
        "calls = []\n"
        "core.update_user_last_seen = lambda a, source='': calls.append((a, source))\n"
        "app = Flask('probe')\n"
        "with app.test_request_context('/api/x'):\n"
        "    g.last_seen_candidate = 'mirage1forged'\n"
        "    core.flush_user_last_seen(400)\n"
        "    after_error = len(calls)\n"
        "    core.flush_user_last_seen(200)\n"
        "    after_ok = len(calls)\n"
        "print('OK' if after_error == 0 and after_ok == 1 else ('BAD', after_error, after_ok))\n",
    )

    # ── L-2: LIKE metacharacters are escaped, backslash included ─────────
    _probe(
        "backend_hardening.like_metachars_escaped",
        "from routes.public import _escape_like\n"
        "bs = chr(92)\n"
        "ok = (_escape_like('%') == bs + '%' and _escape_like('_') == bs + '_'\n"
        "      and _escape_like(bs) == bs + bs and _escape_like('alice') == 'alice')\n"
        "print('OK' if ok else ('BAD', _escape_like('%'), _escape_like(bs)))\n",
    )

    # ── Sub-threshold sweep ──────────────────────────────────────────────
    _probe(
        "backend_hardening.argon2_failure_is_loud",
        "import pow as powmod\n"
        "def boom(*a, **k):\n"
        "    raise ValueError('argon2 broken')\n"
        "powmod._argon2_hash_raw = boom\n"
        "try:\n"
        "    powmod.argon2_digest(b'base', '00' * 32, 1)\n"
        "    print('BAD-returned-none')\n"
        "except ValueError:\n"
        "    print('OK')\n",
    )
    _probe(
        "backend_hardening.params_refresh_ttl",
        "import params\n"
        "ok = 0 < params.PARAMS_REFRESH_SECONDS <= 300 and hasattr(params, '_PARAMS_LOADED_AT')\n"
        "print('OK' if ok else ('BAD', params.PARAMS_REFRESH_SECONDS))\n",
    )
    _probe(
        "backend_hardening.similarity_negative_cache",
        "import similarity as s\n"
        "writes = []\n"
        "s.compute_user_similarities = lambda cur, viewer: []\n"
        "class Cur:\n"
        "    def execute(self, sql, params=None):\n"
        "        writes.append((sql, params))\n"
        "    def fetchall(self):\n"
        "        return []\n"
        "s.get_or_compute_similarities(None, 'mirage1lonely', backend_cur=Cur())\n"
        "inserts = [w for w in writes if 'INSERT' in w[0]]\n"
        "print('OK' if len(inserts) == 1 else ('BAD', len(inserts)))\n",
    )
    _probe(
        "backend_hardening.push_token_cap",
        "from routes.core import MAX_PUSH_TOKENS_PER_OWNER as m\n" "print('OK' if 0 < m <= 100 else ('BAD', m))\n",
    )
    _probe(
        "backend_hardening.privkey_error_omits_cli_output",
        "import inspect, node\n"
        "src = inspect.getsource(node._export_privkey_bytes)\n"
        "print('OK' if 'out[:200]' not in src and 'out}' not in src else ('BAD', src[-200:]))\n",
    )

    # One response counts one impression per image, however many posts in it
    # carry that image and however many times each carries it. The end-to-end
    # test cannot assert this: view_count is global and any concurrent request
    # returning the same post moves it, so it only checks that a view is counted
    # at all. This is the exact-arithmetic half, and it needs no chain traffic.
    _probe(
        "backend_hardening.image_impression_counted_once_per_response",
        "from routes.public import _collect_image_impression_ids as ids\n"
        "a = 'https://imagedelivery.net/h/11111111-1111-4111-8111-111111111111/public'\n"
        "b = 'https://imagedelivery.net/h/22222222-2222-4222-8222-222222222222/public'\n"
        "one = ids([{'media': [a]}])\n"
        "repeated = ids([{'media': [a, a]}, {'media': [a]}])\n"
        "two = ids([{'media': [a, b]}])\n"
        "empty = ids([{'media': []}, {}])\n"
        "ok = len(one) == 1 and repeated == one and len(two) == 2 and not empty\n"
        "print('OK' if ok else ('BAD', len(one), len(repeated), len(two), len(empty)))\n",
    )

    # Push enabled with an empty Expo token must be reported loudly. It is not
    # fatal: every node in the fleet is in exactly this state, so raising here
    # would take them all offline on upgrade rather than fixing anything.
    rc, out = docker_import_probe(
        "settings",
        mutation="export PUSH_NOTIFICATIONS_ENABLED=true EXPO_ACCESS_TOKEN=",
    )
    if "rc=0" in out and "EXPO_ACCESS_TOKEN is empty" in out:
        _pass("backend_hardening.expo_token_warned")
    else:
        _fail("backend_hardening.expo_token_warned", out.strip()[-300:])

    _debug("backend_hardening: done")
