from __future__ import annotations

import json
import os
import re
import time

from tests.common import (
    _pass,
    _fail,
    _debug,
    _keyring_backend,
    _run_miraged,
)
from tests.blockchain_helpers import (
    _get_chain_params,
    _parse_cli_json,
    _require_chain_id,
)
from shared.datatypes import MsgUpdateParams, Params

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PROTO_DIR = os.path.join(REPO_ROOT, "blockchain", "proto", "mirage", "core", "v1")
PROPOSALS_DIR = os.path.join(REPO_ROOT, "scripts", "proposals")
NODE_HOME = "/root/.mirage/node"
NODE_RPC = "tcp://127.0.0.1:26657"
VALIDATOR_KEY = "validator"

# Governance budget: expedited proposals on the local testnet decide in well
# under two minutes. The bound exists so a stuck proposal fails the category
# instead of hanging the suite.
GOV_DEADLINE_SEC = 180
GOV_POLL_SEC = 2

_FIELD_RE = re.compile(
    r"^\s*(?:repeated\s+)?[\w.]+\s+(?P<name>[a-z0-9_]+)\s*=\s*(?P<number>\d+)\s*(?:\[[^\]]*\])?\s*;",
    re.MULTILINE,
)


def _proto_message_body(path: str, message: str) -> str:
    """Return the body of `message X { ... }` from a .proto file.

    Brace counting rather than a regex over the whole file: Params contains
    nested option blocks, and a lazy match would stop at the first '}'.
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    start = text.find(f"message {message} {{")
    if start < 0:
        raise RuntimeError(f"message {message} not found in {path}")
    open_brace = text.index("{", start)
    depth = 0
    for i in range(open_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace + 1 : i]
    raise RuntimeError(f"unterminated message {message} in {path}")


def _proto_fields(path: str, message: str) -> dict[str, int]:
    body = _proto_message_body(path, message)
    # Drop nested messages/enums so their fields are not attributed to the
    # outer message.
    depth = 0
    top_level: list[str] = []
    for line in body.splitlines():
        opens = line.count("{")
        closes = line.count("}")
        if depth == 0 and opens == 0:
            top_level.append(line)
        depth += opens - closes
    fields: dict[str, int] = {}
    for match in _FIELD_RE.finditer("\n".join(top_level)):
        fields[match.group("name")] = int(match.group("number"))
    if not fields:
        raise RuntimeError(f"no fields parsed for {message} in {path}")
    return fields


def _python_fields(message_class) -> dict[str, int]:
    return {f.name: f.number for f in message_class.DESCRIPTOR.fields}


def test_params_schema(backend: str) -> None:
    """Source probe: the Python param mirror and the proposal files must match
    the chain proto exactly. A drifted field number silently decodes governance
    messages into the wrong field, and a proposal without an update_mask is
    rejected by the chain."""

    # 1. Params field names and numbers are identical in proto and Python.
    try:
        proto_params = _proto_fields(os.path.join(PROTO_DIR, "params.proto"), "Params")
        python_params = _python_fields(Params)
        if proto_params == python_params:
            _pass("params_schema.params_fields_match")
        else:
            missing = {k: v for k, v in proto_params.items() if python_params.get(k) != v}
            extra = {k: v for k, v in python_params.items() if proto_params.get(k) != v}
            _fail(
                "params_schema.params_fields_match",
                f"python mirror drifted from proto: proto_only={missing} python_only={extra}",
            )
    except Exception as e:
        _fail("params_schema.params_fields_match", str(e))

    # 2. MsgUpdateParams carries update_mask at field 3 on both sides.
    try:
        proto_msg = _proto_fields(os.path.join(PROTO_DIR, "tx.proto"), "MsgUpdateParams")
        python_msg = _python_fields(MsgUpdateParams)
        if proto_msg == python_msg and proto_msg.get("update_mask") == 3:
            _pass("params_schema.update_mask_present")
        else:
            _fail(
                "params_schema.update_mask_present",
                f"proto={proto_msg} python={python_msg}",
            )
    except Exception as e:
        _fail("params_schema.update_mask_present", str(e))

    # 3. The mask round-trips over the wire, so the indexer sees which fields a
    #    proposal changed.
    try:
        msg = MsgUpdateParams()
        msg.authority = "mirage1testauthority"
        msg.params.pow_message_limit = 0
        msg.update_mask.paths.append("pow_message_limit")
        decoded = MsgUpdateParams()
        decoded.ParseFromString(msg.SerializeToString())
        if list(decoded.update_mask.paths) == ["pow_message_limit"]:
            _pass("params_schema.mask_roundtrip")
        else:
            _fail("params_schema.mask_roundtrip", f"paths={list(decoded.update_mask.paths)}")
    except Exception as e:
        _fail("params_schema.mask_roundtrip", str(e))

    # 4. Every committed MsgUpdateParams proposal masks exactly the params it
    #    supplies. A mismatch means the proposal either silently skips a value
    #    or names a field it never sets.
    try:
        param_names = set(_python_fields(Params))
        checked = 0
        problems: list[str] = []
        for name in sorted(os.listdir(PROPOSALS_DIR)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(PROPOSALS_DIR, name), "r", encoding="utf-8") as f:
                proposal = json.load(f)
            for msg in proposal.get("messages") or []:
                if msg.get("@type") != "/mirage.core.v1.MsgUpdateParams":
                    continue
                checked += 1
                supplied = set((msg.get("params") or {}).keys())
                masked = list(((msg.get("update_mask") or {}).get("paths")) or [])
                if not masked:
                    problems.append(f"{name}: missing update_mask")
                    continue
                if len(masked) != len(set(masked)):
                    problems.append(f"{name}: duplicate mask paths {masked}")
                unknown = sorted(set(masked) - param_names)
                if unknown:
                    problems.append(f"{name}: unknown mask paths {unknown}")
                if set(masked) != supplied:
                    problems.append(f"{name}: mask {sorted(masked)} != params {sorted(supplied)}")
        if checked == 0:
            _fail("params_schema.proposal_masks", "no MsgUpdateParams proposals found")
        elif problems:
            _fail("params_schema.proposal_masks", "; ".join(problems))
        else:
            _pass("params_schema.proposal_masks")
            _debug(f"params_schema: {checked} MsgUpdateParams proposal message(s) verified")
    except Exception as e:
        _fail("params_schema.proposal_masks", str(e))


def _gov_min_deposit(expedited: bool) -> str:
    code, out = _run_miraged(
        ["q", "gov", "params", "--home", NODE_HOME, "--node", NODE_RPC, "-o", "json"],
        timeout=15,
    )
    if code != 0 or not out:
        raise RuntimeError(f"gov params query failed: {out[:200]}")
    data = _parse_cli_json(out) or {}
    params = data.get("params") or data
    key = "expedited_min_deposit" if expedited else "min_deposit"
    for entry in params.get(key) or []:
        if entry.get("denom") == "umirage":
            return f"{entry.get('amount')}umirage"
    raise RuntimeError(f"{key} missing umirage entry")


def _write_mask_proposal(path: str, authority: str, values: dict, paths: list[str], title: str, deposit: str) -> None:
    proposal = {
        "messages": [
            {
                "@type": "/mirage.core.v1.MsgUpdateParams",
                "authority": authority,
                "params": values,
                "update_mask": {"paths": paths},
            }
        ],
        "metadata": "",
        "deposit": deposit,
        "title": title,
        "summary": f"{title} (blockchain suite, local testnet only)",
        "expedited": True,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proposal, f)


def _tx_gov(args: list[str]) -> dict:
    """Run a gov tx from the validator key and return the parsed broadcast
    response. Raises on a non-zero CheckTx code."""
    code, out = _run_miraged(
        args
        + [
            "--from",
            VALIDATOR_KEY,
            "--home",
            NODE_HOME,
            "--keyring-backend",
            _keyring_backend(),
            "--chain-id",
            _require_chain_id(),
            "--node",
            NODE_RPC,
            "--broadcast-mode",
            "sync",
            "--gas",
            "auto",
            "--gas-adjustment",
            "1.5",
            "--gas-prices",
            "5000umirage",
            "--yes",
            "-o",
            "json",
        ],
        timeout=60,
    )
    if code != 0 or not out:
        raise RuntimeError(f"gov tx failed (exit {code}): {out[:300]}")
    resp = _parse_cli_json(out)
    if resp is None:
        raise RuntimeError(f"gov tx: no JSON in output: {out[:300]}")
    if int(resp.get("code", 1)) != 0:
        raise RuntimeError(f"gov tx rejected: code={resp.get('code')} log={str(resp.get('raw_log'))[:300]}")
    return resp


def _find_proposal_id(title: str) -> str:
    """Find the proposal id for a title. Queries voting-period proposals so old
    passed proposals (which may reference removed message types) are not
    deserialized."""
    for status in ("voting-period", "deposit-period"):
        code, out = _run_miraged(
            [
                "q",
                "gov",
                "proposals",
                "--proposal-status",
                status,
                "--home",
                NODE_HOME,
                "--node",
                NODE_RPC,
                "-o",
                "json",
            ],
            timeout=20,
        )
        # A rejected flag or an unreachable node must not read as "no such
        # proposal": that turns a broken query into a timeout ten minutes later.
        if code != 0:
            raise RuntimeError(f"gov proposals query failed (exit {code}): {out[:300]}")
        if not out:
            continue
        data = _parse_cli_json(out) or {}
        for proposal in reversed(data.get("proposals") or []):
            if proposal.get("title") == title:
                return str(proposal.get("id"))
    return ""


def _proposal_status(proposal_id: str) -> str:
    code, out = _run_miraged(
        ["q", "gov", "proposal", proposal_id, "--home", NODE_HOME, "--node", NODE_RPC, "-o", "json"],
        timeout=20,
    )
    if code != 0 or not out:
        return ""
    data = _parse_cli_json(out) or {}
    proposal = data.get("proposal") or data
    return str(proposal.get("status") or "")


def _pass_masked_proposal(authority: str, values: dict, paths: list[str], title: str) -> None:
    """Submit, vote and wait for a masked MsgUpdateParams proposal to pass.
    Raises with a clear message on any failure or on the time budget."""
    deposit = _gov_min_deposit(expedited=True)
    path = f"/tmp/mirage_params_mask_{int(time.time() * 1000)}.json"
    _write_mask_proposal(path, authority, values, paths, title, deposit)
    _debug(f"params_mask: submitting {title} paths={paths} values={values} deposit={deposit}")

    _tx_gov(["tx", "gov", "submit-proposal", path])
    os.remove(path)

    deadline = time.time() + GOV_DEADLINE_SEC
    proposal_id = ""
    while time.time() < deadline and not proposal_id:
        time.sleep(GOV_POLL_SEC)
        proposal_id = _find_proposal_id(title)
    if not proposal_id:
        raise RuntimeError(f"proposal {title!r} never reached voting/deposit period")
    _debug(f"params_mask: proposal_id={proposal_id}")

    _tx_gov(["tx", "gov", "vote", proposal_id, "yes"])

    while time.time() < deadline:
        time.sleep(GOV_POLL_SEC)
        status = _proposal_status(proposal_id)
        if status == "PROPOSAL_STATUS_PASSED":
            _debug(f"params_mask: proposal {proposal_id} passed")
            return
        if status in ("PROPOSAL_STATUS_REJECTED", "PROPOSAL_STATUS_FAILED"):
            raise RuntimeError(f"proposal {proposal_id} ended as {status}")
    raise RuntimeError(f"proposal {proposal_id} did not pass within {GOV_DEADLINE_SEC}s")


def test_params_mask_governance(backend: str) -> None:
    """Governance can set a masked parameter to zero and leaves every unmasked
    parameter untouched (review L-9). Runs against the local testnet only.

    pow_difficulty_allowance is the subject because zero simply removes the
    difficulty-change grace window, and the original value is restored at the
    end of the test.
    """
    field = "pow_difficulty_allowance"
    try:
        before = _get_chain_params()
    except Exception as e:
        _fail("params_mask.query_before", str(e))
        return

    original = str(before.get(field, ""))
    if original == "":
        _fail("params_mask.query_before", f"{field} missing from queried params")
        return
    if original == "0":
        _fail(
            "params_mask.precondition",
            f"{field} is already 0; the zero-value proof needs a non-zero starting value",
        )
        return

    authority = ""
    try:
        from tests.blockchain_helpers import _get_gov_module_address

        authority = _get_gov_module_address()
    except Exception as e:
        _fail("params_mask.gov_authority", str(e))
        return

    title = f"Suite mask zero {field} {int(time.time())}"
    applied = False
    try:
        try:
            _pass_masked_proposal(authority, {field: "0"}, [field], title)
            applied = True
            _pass("params_mask.zero_proposal_passed")
        except Exception as e:
            _fail("params_mask.zero_proposal_passed", str(e))
            return

        try:
            after = _get_chain_params()
        except Exception as e:
            _fail("params_mask.query_after", str(e))
            return

        if str(after.get(field)) == "0":
            _pass("params_mask.masked_zero_applied")
        else:
            _fail("params_mask.masked_zero_applied", f"{field}={after.get(field)!r}, expected 0")

        changed = [
            k
            for k in before
            if k != field and json.dumps(before[k], sort_keys=True) != json.dumps(after.get(k), sort_keys=True)
        ]
        if changed:
            _fail("params_mask.unmasked_fields_untouched", f"unmasked fields changed: {changed}")
        else:
            _pass("params_mask.unmasked_fields_untouched")
    finally:
        if applied:
            restore_title = f"Suite restore {field} {int(time.time())}"
            try:
                _pass_masked_proposal(authority, {field: original}, [field], restore_title)
                restored = _get_chain_params()
                if str(restored.get(field)) == original:
                    _pass("params_mask.restored")
                else:
                    _fail("params_mask.restored", f"{field}={restored.get(field)!r}, expected {original}")
            except Exception as e:
                _fail("params_mask.restored", str(e))
