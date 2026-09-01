"""Push delivery durability tests.

The listener used to insert `push_event_seen` and then hand the notification to
a daemon thread, so a crash, an Expo outage, or a missing profile lost the push
forever while the source cursor moved past it. These tests pin the replacement:
events are queued in the same transaction that advances the cursor, and a queued
row is only settled once its delivery outcome is known.

The node's own listener is running against the same database, so probe rows are
parked outside its due window and processed with an explicit tick clock. That
keeps every assertion about a row that only the probe can reach.
"""

from __future__ import annotations

import json
import os

from tests.common import (
    _pass,
    _fail,
    _debug,
    _check_local_docker,
    docker_python,
    resolve_db_name,
    _docker_exec,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Each probe is its own process inside the container, which is what makes the
# recovery tests meaningful: every call is a fresh listener start.
_PREAMBLE = (
    "import json, secrets, time\n"
    "import sys\n"
    "sys.path.insert(0, '/opt/mirage')\n"
    "sys.path.insert(0, '/opt/mirage/web/backend')\n"
    "from db import connect_backend_db\n"
    "import push_events, push_listener\n"
    "from shared.push import PUSH_SENT, PUSH_DISCARD, PUSH_RETRY\n"
    "def emit(payload):\n"
    "    print('RESULT:' + json.dumps(payload))\n"
    "def key():\n"
    "    return 'test:outbox:' + secrets.token_hex(8)\n"
    # Parked ten minutes ahead so the node's live listener never sees these rows as
    # due; the probe supplies its own tick clock instead.
    "TICK = int(time.time()) + 600\n"
    "def queue(event_key, created_at=None):\n"
    "    with connect_backend_db() as conn:\n"
    "        with conn.transaction():\n"
    "            with conn.cursor() as cur:\n"
    "                payload = {'poster': 'mirage1probe', 'poster_username': 'probe',\n"
    "                           'target_txhash': 'a' * 64, 'content': event_key,\n"
    "                           'tx_hash': event_key, 'created_at': 0}\n"
    "                ok = push_events.enqueue_push_event(cur, event_key, 'reply', payload,\n"
    "                                                    int(created_at if created_at else time.time()))\n"
    "                cur.execute('UPDATE push_event_seen SET next_attempt_at = %s WHERE event_key = %s',\n"
    "                            (TICK, event_key))\n"
    "    return ok\n"
    "def row(event_key):\n"
    "    with connect_backend_db() as conn:\n"
    "        with conn.cursor() as cur:\n"
    "            cur.execute('SELECT status, attempts, next_attempt_at, last_error, completed_at "
    "FROM push_event_seen WHERE event_key = %s', (event_key,))\n"
    "            r = cur.fetchone()\n"
    "    return list(r) if r else None\n"
    "def drop(event_key):\n"
    "    with connect_backend_db() as conn:\n"
    "        with conn.cursor() as cur:\n"
    "            cur.execute('DELETE FROM push_event_seen WHERE event_key = %s', (event_key,))\n"
    "def stub(outcome, seen):\n"
    "    def deliver(event_type, payload):\n"
    "        seen.append(payload.get('tx_hash'))\n"
    "        return outcome\n"
    "    push_listener.deliver_push_event = deliver\n"
)


def _probe(code: str) -> dict:
    """Run a probe in the container and return its emitted RESULT payload."""
    rc, out = docker_python(_PREAMBLE + code, timeout=180)
    marker = "RESULT:"
    for line in out.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise RuntimeError(f"probe produced no RESULT (rc={rc}): {out[-600:]}")


def _psql(db_name: str, sql: str) -> tuple[int, str]:
    return _docker_exec(f'su - postgres -c "psql -d {db_name} -tAc \\"{sql}\\" 2>&1"', timeout=15)


def test_push_outbox_schema(backend: str):
    """The outbox columns exist, statuses are constrained, and old rows are terminal."""
    del backend

    if not _check_local_docker():
        _fail("push_outbox_schema.columns_present", "local docker required")
        return

    db_name = resolve_db_name("BACKEND_DB_URL")
    if not db_name:
        _fail("push_outbox_schema.columns_present", "BACKEND_DB_URL not resolvable")
        return

    rc, out = _psql(
        db_name,
        "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM information_schema.columns "
        "WHERE table_name = 'push_event_seen'",
    )
    expected = {
        "event_key",
        "event_type",
        "created_at",
        "payload",
        "status",
        "attempts",
        "next_attempt_at",
        "completed_at",
        "last_error",
    }
    got = {c for c in out.strip().split(",") if c}
    if rc == 0 and got == expected:
        _pass("push_outbox_schema.columns_present", columns=len(got))
    else:
        _fail("push_outbox_schema.columns_present", f"push_event_seen columns {sorted(got)} != {sorted(expected)}")

    rc, out = _psql(
        db_name,
        "INSERT INTO push_event_seen (event_key, event_type, created_at, status) "
        "VALUES ('test:outbox:bogus', 'reply', 0, 'bogus')",
    )
    if "push_event_seen_status_valid" in out:
        _pass("push_outbox_schema.status_constrained")
    else:
        _fail("push_outbox_schema.status_constrained", f"bogus status was not rejected: rc={rc} out={out[:200]}")

    rc, out = _psql(
        db_name,
        "INSERT INTO push_event_seen (event_key, event_type, created_at, status) "
        "VALUES ('test:outbox:null-payload', 'reply', 0, 'pending')",
    )
    if "push_event_seen_pending_payload" in out:
        _pass("push_outbox_schema.pending_payload_required")
    else:
        _fail(
            "push_outbox_schema.pending_payload_required",
            f"pending row without payload was accepted: rc={rc} out={out[:200]}",
        )

    rc, out = _psql(
        db_name,
        "INSERT INTO push_event_seen (event_key, event_type, created_at, payload, status) "
        "VALUES ('test:outbox:scalar-payload', 'reply', 0, '[]'::jsonb, 'pending')",
    )
    if "push_event_seen_pending_payload_object" in out:
        _pass("push_outbox_schema.pending_payload_must_be_object")
    else:
        _fail(
            "push_outbox_schema.pending_payload_must_be_object",
            f"pending row with non-object payload was accepted: rc={rc} out={out[:200]}",
        )

    # Rows written before the outbox existed were delivered (or lost) by the old
    # path; they must not come back as pending work.
    rc, out = _psql(
        db_name,
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'push_event_seen' AND column_name = 'status'",
    )
    if rc == 0 and "'sent'" in out:
        _pass("push_outbox_schema.legacy_rows_are_terminal")
    else:
        _fail("push_outbox_schema.legacy_rows_are_terminal", f"status default is not 'sent': {out[:200]}")


def test_push_outbox_enqueue(backend: str):
    """Queueing is idempotent and commits with the cursor that produced it."""
    del backend

    if not _check_local_docker():
        _fail("push_outbox_enqueue.deduplicates", "local docker required")
        return

    dedupe = _probe(
        "k = key()\n"
        "first = queue(k)\n"
        "second = queue(k)\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('SELECT count(*) FROM push_event_seen WHERE event_key = %s', (k,))\n"
        "        count = cur.fetchone()[0]\n"
        "state = row(k)\n"
        "drop(k)\n"
        "emit({'first': first, 'second': second, 'count': count, 'status': state[0]})\n"
    )
    if dedupe["first"] and not dedupe["second"] and dedupe["count"] == 1 and dedupe["status"] == "pending":
        _pass("push_outbox_enqueue.deduplicates")
    else:
        _fail("push_outbox_enqueue.deduplicates", f"duplicate enqueue was not absorbed: {dedupe}")

    mention_keys = _probe(
        "alice = push_events.mention_event_key('A' * 64, 'Alice')\n"
        "bob = push_events.mention_event_key('A' * 64, 'Bob')\n"
        "emit({'distinct': alice != bob, 'alice': alice})\n"
    )
    if mention_keys["distinct"] and mention_keys["alice"].endswith(":alice"):
        _pass("push_outbox_enqueue.mentions_are_per_recipient")
    else:
        _fail(
            "push_outbox_enqueue.mentions_are_per_recipient",
            f"one outbox row still covers multiple recipients: {mention_keys}",
        )

    # The cursor advance and the rows it produced share one transaction: if the
    # batch dies halfway, the listener must re-read the same source rows.
    atomic = _probe(
        "k = key()\n"
        "ts = int(time.time())\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('INSERT INTO push_event_cursor (event_type, last_created_at, last_id, updated_at) "
        "VALUES (%s, 0, %s, %s) ON CONFLICT (event_type) DO UPDATE SET last_created_at = 0, last_id = %s',\n"
        "            ('test_outbox', 'before', ts, 'before'))\n"
        "crashed = False\n"
        "try:\n"
        "    with connect_backend_db() as conn:\n"
        "        with conn.transaction():\n"
        "            with conn.cursor() as cur:\n"
        "                push_events.enqueue_push_event(cur, k, 'reply', {'created_at': ts}, ts)\n"
        "                push_listener._update_cursor(cur, 'test_outbox', 999, 'after')\n"
        "                raise RuntimeError('crash mid-batch')\n"
        "except RuntimeError:\n"
        "    crashed = True\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('SELECT last_id FROM push_event_cursor WHERE event_type = %s', ('test_outbox',))\n"
        "        cursor_id = cur.fetchone()[0]\n"
        "        cur.execute('DELETE FROM push_event_cursor WHERE event_type = %s', ('test_outbox',))\n"
        "emit({'crashed': crashed, 'cursor': cursor_id, 'queued': row(k) is not None})\n"
    )
    if atomic["crashed"] and atomic["cursor"] == "before" and not atomic["queued"]:
        _pass("push_outbox_enqueue.cursor_is_atomic")
    else:
        _fail("push_outbox_enqueue.cursor_is_atomic", f"cursor and outbox rows did not roll back together: {atomic}")


def test_push_outbox_delivery(backend: str):
    """A queued push survives a restart and is delivered exactly once."""
    del backend

    if not _check_local_docker():
        _fail("push_outbox_delivery.survives_restart", "local docker required")
        return

    queued = _probe(
        # Process exits right here: the old code had already marked this event
        # seen and moved the cursor past it.
        "k = key()\n"
        "queue(k)\n"
        "emit({'key': k, 'state': row(k)})\n"
    )
    event_key = queued["key"]
    if queued["state"][0] == "pending":
        _pass("push_outbox_delivery.pending_before_send")
    else:
        _fail("push_outbox_delivery.pending_before_send", f"queued row is not pending: {queued}")
        return
    _debug(f"push outbox queued key={event_key} state={queued['state']}")

    recovered = _probe(
        f"k = '{event_key}'\n"
        "seen = []\n"
        "stub(PUSH_SENT, seen)\n"
        "push_listener._process_outbox(now_ts=TICK)\n"
        "after_first = row(k)\n"
        "push_listener._process_outbox(now_ts=TICK)\n"
        "after_second = row(k)\n"
        "drop(k)\n"
        "emit({'deliveries': seen.count(k), 'status': after_first[0], 'still': after_second[0]})\n"
    )
    if recovered["deliveries"] == 1 and recovered["status"] == "sent" and recovered["still"] == "sent":
        _pass("push_outbox_delivery.survives_restart")
    else:
        _fail("push_outbox_delivery.survives_restart", f"restart did not deliver exactly once: {recovered}")

    # Nothing to deliver to (no device, self-notification) is terminal, not a
    # retry: the push would never become deliverable.
    discarded = _probe(
        "k = key()\n"
        "queue(k)\n"
        "seen = []\n"
        "stub(PUSH_DISCARD, seen)\n"
        "push_listener._process_outbox(now_ts=TICK)\n"
        "state = row(k)\n"
        "drop(k)\n"
        "emit({'status': state[0], 'attempts': state[1]})\n"
    )
    if discarded["status"] == "discarded" and discarded["attempts"] == 0:
        _pass("push_outbox_delivery.discard_is_terminal")
    else:
        _fail("push_outbox_delivery.discard_is_terminal", f"undeliverable push was not discarded: {discarded}")


def test_push_outbox_retry(backend: str):
    """Failed delivery backs off, then goes terminal instead of retrying forever."""
    del backend

    if not _check_local_docker():
        _fail("push_outbox_retry.backs_off", "local docker required")
        return

    retried = _probe(
        "k = key()\n"
        "queue(k)\n"
        "seen = []\n"
        "stub(PUSH_RETRY, seen)\n"
        "push_listener._process_outbox(now_ts=TICK)\n"
        "state = row(k)\n"
        # Still pending but no longer due, so the next tick does not hammer Expo.
        "push_listener._process_outbox(now_ts=TICK)\n"
        "drop(k)\n"
        "emit({'status': state[0], 'attempts': state[1], 'due_in': state[2] - TICK,\n"
        "      'deliveries': seen.count(k)})\n"
    )
    if (
        retried["status"] == "pending"
        and retried["attempts"] == 1
        and retried["due_in"] > 0
        and retried["deliveries"] == 1
    ):
        _pass("push_outbox_retry.backs_off", due_in=retried["due_in"])
    else:
        _fail("push_outbox_retry.backs_off", f"failed delivery was not rescheduled: {retried}")

    exhausted = _probe(
        "k = key()\n"
        "queue(k)\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('UPDATE push_event_seen SET attempts = %s WHERE event_key = %s',\n"
        "            (push_events.PUSH_OUTBOX_MAX_ATTEMPTS - 1, k))\n"
        "seen = []\n"
        "stub(PUSH_RETRY, seen)\n"
        "push_listener._process_outbox(now_ts=TICK)\n"
        "state = row(k)\n"
        "drop(k)\n"
        "emit({'status': state[0], 'attempts': state[1], 'error': state[3]})\n"
    )
    if exhausted["status"] == "failed" and exhausted["error"]:
        _pass("push_outbox_retry.exhaustion_is_terminal", attempts=exhausted["attempts"])
    else:
        _fail("push_outbox_retry.exhaustion_is_terminal", f"retries never stopped: {exhausted}")

    aged = _probe(
        "k = key()\n"
        "queue(k, created_at=TICK - push_events.PUSH_OUTBOX_MAX_AGE_SECONDS - 60)\n"
        "seen = []\n"
        "stub(PUSH_RETRY, seen)\n"
        "push_listener._process_outbox(now_ts=TICK)\n"
        "state = row(k)\n"
        "drop(k)\n"
        "emit({'status': state[0], 'attempts': state[1], 'deliveries': seen.count(k)})\n"
    )
    if aged["status"] == "failed" and aged["attempts"] == 1 and aged["deliveries"] == 0:
        _pass("push_outbox_retry.stale_event_is_dropped")
    else:
        _fail("push_outbox_retry.stale_event_is_dropped", f"a stale push was delivered or kept retrying: {aged}")

    throttle = _probe(
        "from shared import push as shared_push\n"
        "owner = 'mirage1throttle' + secrets.token_hex(10)\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('DELETE FROM push_throttle WHERE owner = %s', (owner,))\n"
        "shared_push._send_expo_push_batch = lambda messages: []\n"
        "outcome = shared_push._send_push_to_user(\n"
        "    owner, 'title', 'body', {'type': 'reply', 'replyId': 'test'}, "
        "tokens=[('ExponentPushToken[test]', 'ios')]\n"
        ")\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('SELECT sent_count FROM push_throttle WHERE owner = %s', (owner,))\n"
        "        sent_count = cur.fetchone()[0]\n"
        "        cur.execute('DELETE FROM push_throttle WHERE owner = %s', (owner,))\n"
        "emit({'outcome': outcome, 'sent_count': sent_count})\n"
    )
    if throttle["outcome"] == "retry" and throttle["sent_count"] == 0:
        _pass("push_outbox_retry.failed_expo_send_releases_throttle_slot")
    else:
        _fail(
            "push_outbox_retry.failed_expo_send_releases_throttle_slot",
            f"failed delivery consumed the retry's throttle budget: {throttle}",
        )

    db_failure = _probe(
        "from shared import push as shared_push\n"
        "def broken_db():\n"
        "    raise RuntimeError('backend db unavailable')\n"
        "shared_push._connect_backend_db = broken_db\n"
        "try:\n"
        "    shared_push._get_tokens_for_owner('mirage1probe')\n"
        "    raised = False\n"
        "except RuntimeError:\n"
        "    raised = True\n"
        "emit({'raised': raised})\n"
    )
    if db_failure["raised"]:
        _pass("push_outbox_retry.db_failure_is_retryable")
    else:
        _fail(
            "push_outbox_retry.db_failure_is_retryable",
            "a push-token database outage was mistaken for a user with no devices",
        )


def test_push_outbox_cleanup(backend: str):
    """The dedup sweep never deletes work that has not been delivered."""
    del backend

    if not _check_local_docker():
        _fail("push_outbox_cleanup.keeps_pending", "local docker required")
        return

    swept = _probe(
        "pending_key = key()\n"
        "sent_key = key()\n"
        "old = int(time.time()) - push_listener.PUSH_EVENT_SEEN_TTL_SECONDS - 3600\n"
        "queue(pending_key, created_at=old)\n"
        "queue(sent_key, created_at=old)\n"
        "push_events.mark_push_event_sent(sent_key)\n"
        "push_listener._maybe_cleanup_seen()\n"
        "state_pending = row(pending_key)\n"
        "state_sent = row(sent_key)\n"
        "drop(pending_key)\n"
        "drop(sent_key)\n"
        "emit({'pending_kept': state_pending is not None, 'sent_deleted': state_sent is None})\n"
    )
    if swept["pending_kept"] and swept["sent_deleted"]:
        _pass("push_outbox_cleanup.keeps_pending")
    else:
        _fail("push_outbox_cleanup.keeps_pending", f"cleanup did not preserve undelivered work: {swept}")

    listener_src = open(os.path.join(REPO_ROOT, "web", "backend", "push_listener.py"), encoding="utf-8").read()
    if "_fire_and_forget" not in listener_src and "mark_push_event_seen" not in listener_src:
        _pass("push_outbox_cleanup.no_predelivery_dedup")
    else:
        _fail(
            "push_outbox_cleanup.no_predelivery_dedup",
            "the listener still marks events seen before delivery completes",
        )
