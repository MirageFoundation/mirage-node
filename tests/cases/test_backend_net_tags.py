"""Checks for the v1.36.1 epoch-scoped network tags.

Two halves. The format and the keyed construction are pure functions with no
node dependency, so they run in-process here. Anything that touches the backend
runtime — the memo the transaction builder actually emits, the import-time key
requirement — runs through `docker_python` against the deployed tree, because
that is the code the node serves.

The properties worth defending, and what breaks if each is lost:

  * Determinism within an epoch. Lose it and no two transactions from one
    network ever share a tag, which is the entire signal.
  * Rotation across epochs. Lose it and tags become a permanent public
    pseudonym for a network rather than a week-long one.
  * Key dependence. Lose it and anyone can recompute the whole IPv4 table.
  * /64 bucketing on IPv6. Lose it and RFC 4941 privacy addresses give every
    request from one subscriber a different tag.
  * The parser never raising. Any fee-paying relayer writes the memo, so a
    parser that throws is an indexer-kill primitive reachable from the chain.
  * One memo per request. The transaction is built up to four times per request
    and all of them must be byte-identical, or the simulated size differs from
    the broadcast size.

`test_net_tags_live` is the separate online half. It spends wallets and chain
time, so it is its own category, but without it every check above can pass while
not a single tag ever reaches the chain.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _rand_str,
    docker_python,
    docker_import_probe,
    _docker_exec,
    WALLETS,
)
from tests.backend_helpers import (
    _do_post,
    _do_vote,
    _wait_indexed,
)

_REPO = Path(__file__).resolve().parents[2]

if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from shared.nettag import STATUS_VALID, encode_memo, parse_memo  # noqa: E402


def _probe(name: str, code: str, *, timeout: int = 60) -> None:
    rc, out = docker_python(code, timeout=timeout)
    if "rc=0" in out and "OK" in out and "BAD" not in out:
        _pass(name)
    else:
        _fail(name, f"rc={rc} out={out.strip()[-400:]}")


def _import_shared():
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from shared import nettag

    return nettag


def _test_memo_format() -> None:
    """Encode/decode round trip, and the vocabulary the encoder may emit."""
    nettag = _import_shared()

    namespace = nettag.b64u_encode(bytes(range(nettag.NAMESPACE_BYTES)))
    tag = nettag.b64u_encode(bytes(range(nettag.TAG_BYTES)))

    memo = nettag.encode_memo(namespace, "2026-W33", 4, tag, "hosting")
    parsed = nettag.parse_memo(memo)
    if parsed.status != nettag.STATUS_VALID:
        _fail("net_tags.memo_round_trip", f"{parsed.status}: {parsed.reason}")
        return
    mismatches = {
        k: (got, want)
        for k, got, want in (
            ("namespace", parsed.namespace, namespace),
            ("epoch", parsed.epoch, "2026-W33"),
            ("family", parsed.family, 4),
            ("tag", parsed.tag, tag),
            ("net_class", parsed.net_class, "hosting"),
        )
        if got != want
    }
    if mismatches:
        _fail("net_tags.memo_round_trip", f"fields changed across the round trip: {mismatches}")
        return
    _pass("net_tags.memo_round_trip")

    # An omitted class must decode as None, never as the string "unknown". They
    # are different claims: "no data at all" versus "consulted and no match".
    without = nettag.parse_memo(nettag.encode_memo(namespace, "2026-W33", 6, tag, None))
    if without.net_class is not None:
        _fail("net_tags.absent_class_is_none", f"got {without.net_class!r}")
    else:
        _pass("net_tags.absent_class_is_none")

    # Every legal shape has to stay inside the chain's memo budget, including
    # the longest class name.
    longest = max(nettag.NET_CLASSES, key=len)
    size = len(nettag.encode_memo(namespace, "2026-W33", 6, tag, longest).encode("ascii"))
    if size > nettag.MEMO_MAX_BYTES:
        _fail("net_tags.memo_within_budget", f"{size} > {nettag.MEMO_MAX_BYTES}")
    else:
        _pass("net_tags.memo_within_budget", bytes=size, budget=nettag.MEMO_MAX_BYTES)


def _test_parser_is_hostile_safe() -> None:
    """The memo is attacker-controlled. The parser must classify, never raise."""
    nettag = _import_shared()

    good_ns = nettag.b64u_encode(b"\x00" * nettag.NAMESPACE_BYTES)
    good_tag = nettag.b64u_encode(b"\x00" * nettag.TAG_BYTES)

    # (memo, expected status). Absent means "not ours, ignore quietly";
    # invalid means "claims to be ours and is malformed", which is logged.
    cases = [
        (None, nettag.STATUS_ABSENT),
        ("", nettag.STATUS_ABSENT),
        ("just a normal user memo", nettag.STATUS_ABSENT),
        ('{"other":{"v":1}}', nettag.STATUS_ABSENT),
        ("[1,2,3]", nettag.STATUS_ABSENT),
        ("x" * 100_000, nettag.STATUS_ABSENT),
        ('{"nettag":' + "[" * 5000 + "]" * 5000 + "}", nettag.STATUS_INVALID),
        ('{"nettag":null}', nettag.STATUS_INVALID),
        ('{"nettag":{}}', nettag.STATUS_INVALID),
        ('{"nettag":{"v":"1"}}', nettag.STATUS_INVALID),
        # bool is an int subclass in Python; True must not pass as version 1.
        (f'{{"nettag":{{"v":true,"n":"{good_ns}","e":"2026-W33","f":4,"t":"{good_tag}"}}}}', nettag.STATUS_INVALID),
        (f'{{"nettag":{{"v":2,"n":"{good_ns}","e":"2026-W33","f":4,"t":"{good_tag}"}}}}', nettag.STATUS_INVALID),
        (f'{{"nettag":{{"v":1,"n":"short","e":"2026-W33","f":4,"t":"{good_tag}"}}}}', nettag.STATUS_INVALID),
        (f'{{"nettag":{{"v":1,"n":"{good_ns}","e":"2026-W00","f":4,"t":"{good_tag}"}}}}', nettag.STATUS_INVALID),
        (f'{{"nettag":{{"v":1,"n":"{good_ns}","e":"2026-W54","f":4,"t":"{good_tag}"}}}}', nettag.STATUS_INVALID),
        (f'{{"nettag":{{"v":1,"n":"{good_ns}","e":"not-an-epoch","f":4,"t":"{good_tag}"}}}}', nettag.STATUS_INVALID),
        (f'{{"nettag":{{"v":1,"n":"{good_ns}","e":"2026-W33","f":5,"t":"{good_tag}"}}}}', nettag.STATUS_INVALID),
        (f'{{"nettag":{{"v":1,"n":"{good_ns}","e":"2026-W33","f":4,"t":"AAAA"}}}}', nettag.STATUS_INVALID),
        (
            f'{{"nettag":{{"v":1,"n":"{good_ns}","e":"2026-W33","f":4,"t":"{good_tag}","c":"residential"}}}}',
            nettag.STATUS_INVALID,
        ),
    ]

    wrong = []
    for memo, expected in cases:
        try:
            got = nettag.parse_memo(memo).status
        except Exception as e:
            wrong.append((str(memo)[:40], f"RAISED {type(e).__name__}: {e}"))
            continue
        if got != expected:
            wrong.append((str(memo)[:40], f"got {got}, want {expected}"))

    if wrong:
        _fail("net_tags.parser_hostile_safe", f"{len(wrong)} case(s) wrong: {wrong[:4]}")
    else:
        _pass("net_tags.parser_hostile_safe", cases=len(cases))

    # Non-canonical base64 must not decode to a valid tag, or one tag would have
    # several spellings and clustering would silently split.
    if nettag.b64u_decode("AAAAAAAAAAB", nettag.NAMESPACE_BYTES) is not None:
        _fail("net_tags.rejects_non_canonical_b64", "a non-canonical namespace decoded")
    else:
        _pass("net_tags.rejects_non_canonical_b64")


def _test_tag_construction() -> None:
    """Determinism, epoch rotation, key dependence and /64 bucketing."""
    code = (
        "import os, sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "os.environ['NET_TAG_HMAC_KEY'] = 'ab' * 32\n"
        "import net_tag\n"
        "from shared.nettag import parse_memo, STATUS_VALID\n"
        "t = lambda ip: parse_memo(net_tag.build_memo(ip)).tag\n"
        "deterministic = t('203.0.113.7') == t('203.0.113.7')\n"
        "distinct = t('203.0.113.7') != t('203.0.113.8')\n"
        "same64 = t('2001:db8:1:2::1') == t('2001:db8:1:2:ffff:ffff:ffff:ffff')\n"
        "diff64 = t('2001:db8:1:2::1') != t('2001:db8:1:3::1')\n"
        "prebucketed = t('2001:db8:1:2::/64') == t('2001:db8:1:2::1')\n"
        "families = parse_memo(net_tag.build_memo('203.0.113.7')).family == 4 and "
        "parse_memo(net_tag.build_memo('2001:db8:1:2::1')).family == 6\n"
        "cross_family = t('203.0.113.7') != t('2001:db8:1:2::1')\n"
        "e1 = net_tag.compute_tag(4, bytes([203,0,113,7]), 2026, 33)\n"
        "e2 = net_tag.compute_tag(4, bytes([203,0,113,7]), 2026, 34)\n"
        "e3 = net_tag.compute_tag(4, bytes([203,0,113,7]), 2027, 33)\n"
        "rotates = e1 != e2 and e1 != e3\n"
        "noip = net_tag.build_memo(None) == '' and net_tag.build_memo('') == '' "
        "and net_tag.build_memo('not-an-ip') == ''\n"
        "ok = deterministic and distinct and same64 and diff64 and prebucketed and families "
        "and cross_family and rotates and noip\n"
        "print('OK' if ok else ('BAD', deterministic, distinct, same64, diff64, prebucketed, "
        "families, cross_family, rotates, noip))\n"
    )
    _probe("net_tags.tag_construction", code)

    # A different key must give a different tag for the same address and epoch.
    # This is the property that makes the tag non-recomputable by an outsider.
    key_code = (
        "import os, sys, subprocess, json\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "out = []\n"
        "for k in ['aa' * 32, 'bb' * 32]:\n"
        "    env = dict(os.environ, NET_TAG_HMAC_KEY=k, PYTHONPATH='/opt/mirage')\n"
        "    src = ('import sys; sys.path.insert(0, chr(47)+chr(111)+chr(112)+chr(116)+chr(47)+"
        "chr(109)+chr(105)+chr(114)+chr(97)+chr(103)+chr(101)+chr(47)+chr(119)+chr(101)+chr(98)+"
        "chr(47)+chr(98)+chr(97)+chr(99)+chr(107)+chr(101)+chr(110)+chr(100)); '\n"
        "           'import net_tag; print(net_tag.build_memo(chr(49)+chr(46)+chr(50)+chr(46)+"
        "chr(51)+chr(46)+chr(52)))')\n"
        "    r = subprocess.run([sys.executable, '-c', src], env=env, capture_output=True, text=True)\n"
        "    out.append(r.stdout.strip())\n"
        "ok = len(out) == 2 and all(out) and out[0] != out[1]\n"
        "print('OK' if ok else ('BAD', out))\n"
    )
    _probe("net_tags.key_dependence", key_code)


def _test_key_required_at_import() -> None:
    """A missing or too-short key must stop the backend, not be worked around.

    Silently skipping tags on a bad key would leave the operator believing the
    feature is on while every transaction goes out untagged.
    """
    for label, mutation in (
        ("missing", "export NET_TAG_HMAC_KEY="),
        ("not_hex", "export NET_TAG_HMAC_KEY=zzzz"),
        ("too_short", "export NET_TAG_HMAC_KEY=abcd"),
    ):
        rc, out = docker_import_probe("net_tag", mutation=mutation)
        if "rc=0" in out:
            _fail(f"net_tags.key_required_{label}", f"import succeeded with a {label} key: {out.strip()[-200:]}")
        elif "NET_TAG_HMAC_KEY" in out:
            _pass(f"net_tags.key_required_{label}")
        else:
            _fail(f"net_tags.key_required_{label}", f"failed without naming the key: {out.strip()[-200:]}")


def _test_tx_builder_emits_one_memo() -> None:
    """The builder must attach the memo, and attach the same bytes every time.

    Both call sites go through _prepare_signed_body, and the per-request cache
    is what makes the estimate, the simulation and the broadcast agree. Asserted
    on the wire bytes rather than on the source, because the memo has to land as
    TxBody field 2 to be readable by anything.
    """
    code = (
        "import sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "import tx\n"
        "from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody\n"
        "memo = tx._append_memo(b'', 'hello')\n"
        "body = TxBody(); body.ParseFromString(memo)\n"
        "attached = body.memo == 'hello'\n"
        "empty_noop = tx._append_memo(b'abc', '') == b'abc'\n"
        # Field order must stay 1, 2, 4, 5 or the body will not decode.
        "full = tx._append_unordered_timeout(tx._append_memo(b'', 'tagged'), 1893456000000000000)\n"
        "parsed = TxBody(); parsed.ParseFromString(full)\n"
        "ordered = parsed.memo == 'tagged'\n"
        "print('OK' if (attached and empty_noop and ordered) else ('BAD', attached, empty_noop, ordered))\n"
    )
    _probe("net_tags.tx_builder_memo_bytes", code)

    # Infrastructure traffic must stay untagged even when it is built inside a
    # claimant's Flask request. This is an explicit tx-builder choice; ambient
    # request context is not a safe discriminator.
    _probe(
        "net_tags.payout_explicitly_untagged",
        "import sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "import tx\n"
        "from flask import Flask\n"
        "from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody\n"
        "app = Flask(__name__)\n"
        "with app.test_request_context('/', environ_base={'REMOTE_ADDR': '203.0.113.9'}):\n"
        "    tagged_raw = tx._prepare_signed_body(b'', 1893456000000000000)\n"
        "    payout_raw = tx._prepare_signed_body(b'', 1893456000000000000, include_request_memo=False)\n"
        "tagged = TxBody(); tagged.ParseFromString(tagged_raw)\n"
        "payout = TxBody(); payout.ParseFromString(payout_raw)\n"
        "print('OK' if tagged.memo and payout.memo == '' else ('BAD', tagged.memo, payout.memo))\n",
    )

    # The production payout path must pass the exclusion through its estimate,
    # simulation build and final build. Spies make this independent of chain
    # state while exercising RewardDistributor.build_payout_tx itself.
    _probe(
        "net_tags.payout_path_declares_exclusion",
        "import sys, types\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "import reward_distributor as rd\n"
        "calls = []\n"
        "addr = 'mirage1vkdacfe53x4ak7redgy6wlegdlglnlst8p47d5'\n"
        "rt = types.SimpleNamespace(rewards_pool_privkey_bytes=b'x'*32, rewards_pool_pubkey_bytes=b'y'*33,\n"
        "    rewards_pool_account_number=1, rewards_pool_addr=addr, min_gas_price_umirage=1)\n"
        "rd.require_runtime = lambda: rt\n"
        "rd.estimate_total_gas_limit = lambda *a, **kw: (calls.append(('estimate', kw)), 100000)[1]\n"
        "rd.build_signed_tx = lambda *a, **kw: (calls.append(('build', kw)), (b'tx', 1893456000000000000))[1]\n"
        "rd.simulate_gas = lambda tx: 50000\n"
        "rd.chain_head = lambda: (100, 0.0)\n"
        "obj = rd.RewardDistributor.__new__(rd.RewardDistributor)\n"
        "obj.pool_address = addr\n"
        "obj.get_pool_balance = lambda: 10**30\n"
        "obj.build_payout_tx(addr, 1)\n"
        "ok = len(calls) == 3 and all(c[1].get('include_request_memo') is False for c in calls)\n"
        "print('OK' if ok else ('BAD', calls))\n",
    )

    # One request, many builds, identical bytes.
    _probe(
        "net_tags.memo_stable_within_request",
        "import sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "import net_tag\n"
        "from flask import Flask\n"
        "app = Flask(__name__)\n"
        "with app.test_request_context('/', environ_base={'REMOTE_ADDR': '203.0.113.9'}):\n"
        "    builds = [net_tag.request_memo() for _ in range(4)]\n"
        "ok = len(set(builds)) == 1 and builds[0] != ''\n"
        "print('OK' if ok else ('BAD', builds))\n",
    )


def _test_asn_classification() -> None:
    """Org keyword mapping, and the None-vs-unknown distinction."""
    if str(_REPO) not in sys.path:
        sys.path.insert(0, str(_REPO))
    from shared.asn_class import classify_org

    cases = [
        ("DIGITALOCEAN-ASN", "hosting"),
        ("Hetzner Online GmbH", "hosting"),
        ("Amazon.com, Inc.", "hosting"),
        ("M247 Europe SRL nordvpn", "vpn"),
        ("Mullvad VPN AB", "vpn"),
        ("Private Internet Access", "vpn"),
        ("T-Mobile USA, Inc.", "cellular"),
        ("China Mobile Communications", "cellular"),
        ("Vodafone Wireless", "cellular"),
        ("Comcast Cable Communications, LLC", "isp"),
        ("Deutsche Telekom AG", "isp"),
        ("", "isp"),
    ]
    wrong = [(org, classify_org(org), want) for org, want in cases if classify_org(org) != want]
    if wrong:
        _fail("net_tags.asn_org_classification", f"{wrong}")
    else:
        _pass("net_tags.asn_org_classification", cases=len(cases))

    # A carrier must never be labelled hosting: that would make ordinary CGNAT
    # look like a deliberate farm, which is the expensive false positive.
    carriers = ["T-Mobile Cloud Services", "Orange Mobile Data Center"]
    misread = [c for c in carriers if classify_org(c) != "cellular"]
    if misread:
        _fail("net_tags.carrier_precedence", f"classified as non-cellular: {misread}")
    else:
        _pass("net_tags.carrier_precedence")

    # With no dataset installed the class is None (omit the key), not "unknown".
    # Pointed at a genuinely empty directory rather than by blanking the cached
    # state, because the reader re-stats and reloads when what is on disk stops
    # matching what it holds.
    _probe(
        "net_tags.no_dataset_yields_none",
        "import sys, os, tempfile\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "os.environ['ASN_DB_DIR'] = tempfile.mkdtemp()\n"
        "import asn_db\n"
        "asn_db._state = None\n"
        "ok = asn_db.classify_ip('203.0.113.7') is None and not asn_db.dataset_status()['available']\n"
        "print('OK' if ok else 'BAD')\n",
    )

    # The ASN dataset is explicitly advisory. Permission errors and mmap
    # failures must omit only the class, never fail the relayed transaction.
    _probe(
        "net_tags.asn_io_failure_yields_none",
        "import sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "import asn_db\n"
        "asn_db._state = None\n"
        "asn_db._load = lambda: (_ for _ in ()).throw(PermissionError('denied'))\n"
        "ok = asn_db.classify_ip('203.0.113.7') is None and asn_db._state is not None\n"
        "print('OK' if ok else 'BAD')\n",
    )


def _test_indexer_attribution_guards() -> None:
    """Only successful, attributable core transactions may create tag rows."""
    _probe(
        "net_tags.relayer_is_bounded",
        "import sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "from indexer.message_processor import relayer_from_message\n"
        "from shared.datatypes import MsgPost\n"
        "valid = 'mirage1vkdacfe53x4ak7redgy6wlegdlglnlst8p47d5'\n"
        "good = MsgPost(); good.authority = valid\n"
        "huge = MsgPost(); huge.authority = 'mirage1' + 'q' * 5000\n"
        "ok = (relayer_from_message('/mirage.core.v1.MsgPost', good.SerializeToString()) == valid\n"
        "      and relayer_from_message('/mirage.core.v1.MsgPost', huge.SerializeToString()) == '')\n"
        "print('OK' if ok else 'BAD')\n",
    )

    _probe(
        "net_tags.failed_and_unattributed_not_projected",
        "import base64, sys, types\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxBody, TxRaw\n"
        "from indexer.main import Indexer\n"
        "from shared.nettag import b64u_encode, encode_memo\n"
        "memo = encode_memo(b64u_encode(b'12345678'), '2026-W34', 4, b64u_encode(b'1'*16), 'isp')\n"
        "raw = TxRaw(body_bytes=TxBody(memo=memo).SerializeToString()).SerializeToString()\n"
        "class DB:\n"
        "    def __init__(self): self.tags = 0; self.failed = 0\n"
        "    def upsert_net_tag(self, *a): self.tags += 1\n"
        "    def upsert_tx_index(self, *a): self.failed += 1\n"
        "idx = Indexer.__new__(Indexer); idx.db = DB()\n"
        "idx._process_tx(0, base64.b64encode(raw).decode(), {'code': 7, 'log': 'rejected'}, 10, 20)\n"
        "failed_ok = idx.db.failed == 1 and idx.db.tags == 0\n"
        "idx._record_net_tag('a'*64, TxBody(memo=memo), 11, 21)\n"
        "unattributed_ok = idx.db.tags == 0\n"
        "print('OK' if failed_ok and unattributed_ok else ('BAD', idx.db.failed, idx.db.tags))\n",
    )

    import base64
    from cosmpy.protos.cosmos.tx.v1beta1.tx_pb2 import TxRaw
    from indexer.main import Indexer

    body_bytes = bytes([0x12, 0x03, 0xFF, 0xFE, 0xFD])
    raw = TxRaw(body_bytes=body_bytes).SerializeToString()

    class DB:
        def __init__(self):
            self.failed = []

        def upsert_tx_index(self, *a):
            self.failed.append(a)

    idx = Indexer.__new__(Indexer)
    idx.db = DB()
    try:
        idx._process_tx(0, base64.b64encode(raw).decode(), {"code": 0}, 10, 20)
    except Exception as exc:
        _fail("net_tags.undecodable_memo_does_not_abort", str(exc))
        return
    if len(idx.db.failed) != 1 or idx.db.failed[0][1] != "undecodable":
        _fail("net_tags.undecodable_memo_does_not_abort", repr(idx.db.failed))
        return
    _pass("net_tags.undecodable_memo_does_not_abort")


def _test_asn_layout_is_shared() -> None:
    """Writer and reader must not redeclare the on-disk layout."""
    layout = Path(_REPO, "shared", "asn_layout.py").read_text(encoding="utf-8")
    if "MAGIC_V4 = b" not in layout or "CLASS_TO_CODE" not in layout:
        _fail("net_tags.asn_layout.missing", "shared/asn_layout.py is not the layout definition")
        return
    for rel in ("web/backend/asn_db.py", "deploy/refresh_asn_db.py"):
        body = Path(_REPO, rel).read_text(encoding="utf-8")
        if "MAGIC_V4 = b" in body or "CLASS_TO_CODE = {" in body:
            _fail("net_tags.asn_layout.duplicated", f"{rel} still declares the ASN layout")
            return
        if "from shared.asn_layout import" not in body:
            _fail("net_tags.asn_layout.not_imported", f"{rel} does not import shared.asn_layout")
            return
    _pass("net_tags.asn_layout.single_definition")


def _test_asn_binary_lookup() -> None:
    """Build a small dataset with the real writer and read it with the real reader.

    Covers the boundary conditions binary search gets wrong: the first and last
    address of a range, and an address in a gap between ranges.
    """
    code = (
        "import sys, tempfile, os\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('refresh_asn_db', "
        "'/opt/mirage/deploy/refresh_asn_db.py')\n"
        "refresh = importlib.util.module_from_spec(spec); spec.loader.exec_module(refresh)\n"
        "import asn_db, ipaddress, json, time\n"
        "d = tempfile.mkdtemp()\n"
        "v4 = [(int(ipaddress.ip_address('10.0.0.0')), int(ipaddress.ip_address('10.0.0.255')), 2),\n"
        "      (int(ipaddress.ip_address('10.0.2.0')), int(ipaddress.ip_address('10.0.2.255')), 3)]\n"
        "v6 = [(0x20010db800010000 >> 0, 0x20010db80001ffff, 4)]\n"
        "refresh._write_table(__import__('pathlib').Path(d + '/asn_v4.bin'), refresh.MAGIC_V4, "
        "refresh.V4_RECORD, v4)\n"
        "refresh._write_table(__import__('pathlib').Path(d + '/asn_v6.bin'), refresh.MAGIC_V6, "
        "refresh.V6_RECORD, v6)\n"
        "open(d + '/meta.json', 'w').write(json.dumps({'built_at': int(time.time())}))\n"
        "os.environ['ASN_DB_DIR'] = d\n"
        "asn_db._state = None\n"
        "first = asn_db.classify_ip('10.0.0.0') == 'hosting'\n"
        "last = asn_db.classify_ip('10.0.0.255') == 'hosting'\n"
        "mid = asn_db.classify_ip('10.0.0.128') == 'hosting'\n"
        "second = asn_db.classify_ip('10.0.2.5') == 'vpn'\n"
        "gap = asn_db.classify_ip('10.0.1.5') == 'unknown'\n"
        "below = asn_db.classify_ip('9.255.255.255') == 'unknown'\n"
        "above = asn_db.classify_ip('10.0.3.0') == 'unknown'\n"
        "sixty4 = asn_db.classify_ip('2001:db8:1:0::1') == 'cellular'\n"
        "ok = first and last and mid and second and gap and below and above and sixty4\n"
        "print('OK' if ok else ('BAD', first, last, mid, second, gap, below, above, sixty4))\n"
    )
    _probe("net_tags.asn_binary_lookup", code)


def _test_indexer_projection() -> None:
    """net_tags exists with the indexes agents need, and rows land in it."""
    # Single quotes only, and the table name is bound as a parameter: the probe
    # is embedded in a double-quoted shell string, so a double quote here would
    # terminate it and the SQL would reach python3 -c already broken.
    code = (
        "import sys, os\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "import psycopg\n"
        "url = os.environ['INDEXER_DB_URL']\n"
        "with psycopg.connect(url, connect_timeout=10) as c:\n"
        "    with c.cursor() as cur:\n"
        "        cur.execute('select column_name from information_schema.columns "
        "where table_name = %s', ('net_tags',))\n"
        "        cols = set(r[0] for r in cur.fetchall())\n"
        "        cur.execute('select indexname from pg_indexes where tablename = %s', ('net_tags',))\n"
        "        idx = set(r[0] for r in cur.fetchall())\n"
        "want_cols = set(['txhash','namespace','epoch','family','tag','net_class','relayer',"
        "'height','created_at'])\n"
        "want_idx = set(['idx_net_tags_tag','idx_net_tags_created_at','idx_net_tags_relayer_lower',"
        "'idx_net_tags_epoch'])\n"
        "ok = want_cols <= cols and want_idx <= idx\n"
        "print('OK' if ok else ('BAD', sorted(want_cols - cols), sorted(want_idx - idx)))\n"
    )
    _probe("net_tags.indexer_schema", code)


def _net_tag_row(txhash: str) -> dict | None:
    """Read one net_tags row through psql in the container."""
    rc, out = _docker_exec(
        "su - postgres -c \"psql -d "
        + _indexer_db_name()
        + " -tAF'|' -c \\\"SELECT namespace, epoch, family, tag, "
        + "COALESCE(net_class,''), COALESCE(relayer,''), height FROM net_tags "
        + f"WHERE LOWER(txhash) = LOWER('{txhash}');\\\" 2>&1\" ",
        timeout=20,
    )
    if rc != 0:
        raise RuntimeError(f"net_tags query failed rc={rc} out={out}")
    line = out.strip()
    if not line:
        return None
    parts = line.split("|")
    if len(parts) < 7:
        raise RuntimeError(f"unexpected net_tags row: {line!r}")
    return {
        "namespace": parts[0],
        "epoch": parts[1],
        "family": int(parts[2]),
        "tag": parts[3],
        "net_class": parts[4],
        "relayer": parts[5],
        "height": int(parts[6]),
    }


def _wait_net_tag(txhash: str, timeout: float = 30.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = _net_tag_row(txhash)
        if row is not None:
            return row
        time.sleep(1.0)
    return None


def _indexer_db_name() -> str:
    url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not url:
        rc, out = _docker_exec("printenv INDEXER_DB_URL")
        url = out.strip() if rc == 0 else ""
    if not url:
        return "mirage_indexer"
    return urlparse(url).path.lstrip("/")


def test_net_tags_live(backend: str) -> None:
    """End-to-end: real relayed transactions carry tags, and the tags cluster.

    Everything in the offline category can pass while no tag is ever written to
    the chain. This is the check that fails if the memo never leaves the
    backend, never survives the ante chain, or never reaches the indexer.

    The clustering assertion is the point of the whole feature: two actions from
    one client in one week must carry the same tag, or there is no signal to
    detect a farm with.
    """
    _debug("net_tags_live: start")

    wallet = WALLETS.get("sub1")
    other = WALLETS.get("sub2")
    if wallet is None or other is None:
        _skip("net_tags_live.setup", "sub1/sub2 wallets not available")
        return

    first_hash = str(
        _do_post(
            backend,
            wallet,
            topic=f"nettag{_rand_str(4)}",
            title="Network tag end to end",
            content="first tagged action",
        )
        or ""
    ).strip()
    if not first_hash:
        _fail("net_tags_live.post_submitted", "backend returned no txhash for the post")
        return
    if not _wait_indexed(backend, str(wallet.address()), first_hash):
        _fail("net_tags_live.post_submitted", f"post {first_hash[:12]} was never indexed")
        return
    _pass("net_tags_live.post_submitted", txhash=first_hash[:12])

    try:
        row = _wait_net_tag(first_hash)
    except RuntimeError as e:
        _fail("net_tags_live.tag_projected", str(e))
        return
    if row is None:
        _fail(
            "net_tags_live.tag_projected",
            f"no net_tags row for {first_hash[:12]}: the relay is not tagging, or the indexer is not projecting",
        )
        return
    _pass("net_tags_live.tag_projected", **{k: row[k] for k in ("epoch", "family", "net_class")})

    # The stored row must be a well-formed tag, not junk that happened to land.
    rebuilt = encode_memo(
        row["namespace"], row["epoch"], row["family"], row["tag"], row["net_class"] or None
    )
    parsed = parse_memo(rebuilt)
    if parsed.status != STATUS_VALID:
        _fail("net_tags_live.row_is_wellformed", f"{parsed.status}: {parsed.reason} (row={row})")
    else:
        _pass("net_tags_live.row_is_wellformed")

    # Attribution: the relaying node must be recorded, or a reader cannot tell
    # whose claim the tag is and the whole thing is unscoped.
    if not row["relayer"].startswith("mirage1"):
        _fail("net_tags_live.relayer_recorded", f"relayer={row['relayer']!r}")
    else:
        _pass("net_tags_live.relayer_recorded", relayer=row["relayer"])

    # The clustering property, and the exact shape a farm has: a second account,
    # a different action type, one network. If these two rows do not share a tag
    # there is nothing for an agent to cluster on and the feature is inert.
    vote = _do_vote(backend, other, first_hash, 1)
    second_hash = str((vote or {}).get("tx_hash") or (vote or {}).get("txhash") or "").strip()
    if not second_hash:
        _fail("net_tags_live.same_tag_across_accounts", f"no txhash from the vote: {vote}")
        return
    try:
        second = _wait_net_tag(second_hash)
    except RuntimeError as e:
        _fail("net_tags_live.same_tag_across_accounts", str(e))
        return
    if second is None:
        _fail("net_tags_live.same_tag_across_accounts", f"no net_tags row for the vote {second_hash[:12]}")
        return
    if second["tag"] != row["tag"]:
        _fail(
            "net_tags_live.same_tag_across_accounts",
            f"two accounts on one network got different tags ({row['tag']} vs {second['tag']}); "
            "clustering cannot work",
        )
    elif second["epoch"] != row["epoch"]:
        _fail("net_tags_live.same_tag_across_accounts", f"epoch changed mid-test: {row['epoch']} -> {second['epoch']}")
    else:
        _pass("net_tags_live.same_tag_across_accounts", tag=row["tag"])

    _debug("net_tags_live: done")


def test_net_tags(backend: str) -> None:
    """Entry point for the net_tags category.

    Takes the backend URL for signature parity with every other category; these
    checks are offline and never call it.
    """
    _debug("net_tags: start")
    _test_memo_format()
    _test_parser_is_hostile_safe()
    _test_asn_classification()
    _test_tag_construction()
    _test_key_required_at_import()
    _test_tx_builder_emits_one_memo()
    _test_asn_layout_is_shared()
    _test_asn_binary_lookup()
    _test_indexer_projection()
    _test_indexer_attribution_guards()
    _debug("net_tags: done")
