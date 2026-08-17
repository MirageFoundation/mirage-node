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
"""

from __future__ import annotations

import sys
from pathlib import Path

from tests.common import (
    _pass,
    _fail,
    _debug,
    docker_python,
    docker_import_probe,
)

_REPO = Path(__file__).resolve().parents[2]


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

    # Outside a request there is no client, so a payout must carry no memo.
    _probe(
        "net_tags.no_memo_outside_request",
        "import sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "import net_tag\n"
        "print('OK' if net_tag.request_memo() == '' else 'BAD')\n",
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
    _test_asn_binary_lookup()
    _test_indexer_projection()
    _debug("net_tags: done")
