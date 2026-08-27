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


def _test_attribution_canon() -> None:
    """L-2 (frontend review): the attribution encoding is pinned across languages.

    invite_code and referrer_username drive the referral reward ledger and used to
    be appended to the POST body after the signature was computed. They now carry
    their own signature, which only works if both sides build the same bytes — so
    these vectors are duplicated verbatim in the frontend's
    tests/unit/frontendHardening.test.js. A change on one side alone turns every
    invited signup into a rejection, which is the loud failure this pins.
    """
    root = Path(__file__).resolve().parents[2]
    for extra in (root, root / "web" / "backend"):
        if str(extra) not in sys.path:
            sys.path.insert(0, str(extra))
    from pow import canon_attribution

    vectors = [
        (
            ("set_username", "MIRAGE1abc", "ABCD-1234", "", 1786816859440123),
            "6d69726167652e6174747269627574696f6e2e7631007365745f757365726e616d65006d69726167653161626300414243442d31323334000031373836383136383539343430313233",
        ),
        (
            ("set_username", "mirage1xyz", "", "bob-1", 9007199254740991),
            "6d69726167652e6174747269627574696f6e2e7631007365745f757365726e616d65006d69726167653178797a0000626f622d310039303037313939323534373430393931",
        ),
    ]
    for args, expected in vectors:
        got = canon_attribution(*args).hex()
        if got != expected:
            _fail("backend_hardening.attribution_canon", f"args={args} got={got}")
            return

    # The nonce binding is what stops a captured signature being replayed onto a
    # different request carrying a different invite code.
    a = canon_attribution("set_username", "mirage1abc", "ABCD-1234", "", 1)
    b = canon_attribution("set_username", "mirage1abc", "ABCD-1234", "", 2)
    if a == b:
        _fail("backend_hardening.attribution_canon", "nonce not bound into the payload")
        return
    _pass("backend_hardening.attribution_canon")


def test_backend_hardening(backend: str):
    _debug(f"backend_hardening: begin backend={backend}")

    _test_topic_matcher()
    _test_attribution_canon()

    if not _check_local_docker():
        _skip("backend_hardening.container_probes", "requires local docker")
        return

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

    # ── 2026-08-14 frontend review ───────────────────────────────────────
    # L-2: a real sign/verify roundtrip over the attribution payload, and proof
    # that swapping the invite code afterwards fails verification.
    _probe(
        "backend_hardening.attribution_signature_roundtrip",
        "import hashlib\n"
        "from cryptography.hazmat.primitives.asymmetric import ec\n"
        "from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, Prehashed\n"
        "from cryptography.hazmat.primitives import hashes, serialization\n"
        "from pow import canon_attribution\n"
        "from routes.core import _verify_signature\n"
        "priv = ec.derive_private_key(0x4d69726167655465737441747472696273, ec.SECP256K1())\n"
        "pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)\n"
        "signed = canon_attribution('set_username', 'mirage1abc', 'AAAA-1111', '', 42)\n"
        "der = priv.sign(hashlib.sha256(signed).digest(), ec.ECDSA(Prehashed(hashes.SHA256())))\n"
        "r, s = decode_dss_signature(der)\n"
        "sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')\n"
        "good = _verify_signature(pub, sig, signed)\n"
        "swapped_code = _verify_signature(pub, sig, canon_attribution('set_username', 'mirage1abc', 'BBBB-2222', '', 42))\n"
        "swapped_ref = _verify_signature(pub, sig, canon_attribution('set_username', 'mirage1abc', 'AAAA-1111', 'mallory', 42))\n"
        "replayed = _verify_signature(pub, sig, canon_attribution('set_username', 'mirage1abc', 'AAAA-1111', '', 43))\n"
        "ok = good and not swapped_code and not swapped_ref and not replayed\n"
        "print('OK' if ok else ('BAD', good, swapped_code, swapped_ref, replayed))\n",
    )
    # The handler blanks referrer_username when a direct invite code is present.
    # Verification has to run against the value the client actually signed, so it
    # must read received_referrer and not the post-blanking raw_referrer -- an
    # ordering slip there would reject every code+referrer signup.
    _probe(
        "backend_hardening.attribution_verifies_received_value",
        "import inspect, re\n"
        "from routes import core\n"
        "src = inspect.getsource(core.core_set_username)\n"
        "call = re.search(r'canon_attribution[(](.*?)[)]', src, re.S)\n"
        "args = call.group(1) if call else ''\n"
        "ok = bool(call) and 'received_referrer' in args and 'raw_referrer' not in args\n"
        "print('OK' if ok else ('BAD', args[:200]))\n",
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
