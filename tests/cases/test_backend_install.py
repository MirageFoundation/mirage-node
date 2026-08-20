"""Source contracts for the one-command installer, signed manifests, and enrollment."""

from __future__ import annotations

import ast
import fcntl
import http.server
import inspect
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.common import _fail, _pass, _rand_str, _skip, _INSIDE_CONTAINER

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INSTALL_SH = os.path.join(REPO_ROOT, "deploy", "install.sh")
CREATE_VALIDATOR = os.path.join(REPO_ROOT, "deploy", "create_validator.sh")
RELEASE_VERIFY = os.path.join(REPO_ROOT, "deploy", "release_verify.py")
UPDATE_SH = os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-update")
UPGRADE_SH = os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-upgrade")
PUBKEY = os.path.join(REPO_ROOT, "deploy", "hosttools", "pubkey.pem")
NETWORK_JSON = os.path.join(REPO_ROOT, "release", "network.json")
STAKE_PY = os.path.join(REPO_ROOT, "scripts", "stake.py")
VERSION_FILE = os.path.join(REPO_ROOT, "VERSION")
EXPECTED_FP = "679a39294dc9639170ca9cb4010c44cc71dd153fa2029f2e73969bff6d86c0a8"
# Imported or executed by .github/workflows/release.yml.
RELEASE_CI_FILES = ("deploy/release_verify.py", "scripts/finalize_release_manifest.py")


def _install_functions_only() -> str:
    text = Path(INSTALL_SH).read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[-1].strip() != 'main "$@"':
        raise AssertionError('install.sh last line must be main "$@"')
    return "\n".join(lines[:-1]) + "\n"


def _run(cmd, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _shell_function(path: str, name: str) -> str:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"{name}() {{")
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line == "}")
    return "\n".join(lines[start : end + 1]) + "\n"


def _shell_variable(path: str, name: str) -> str:
    """Read a single-quoted top-level shell assignment, unquoted."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}='") and line.endswith("'"):
            return line[len(name) + 2 : -1]
    return ""


def _ed25519_keypair(tmpdir: str) -> tuple[str, str]:
    priv = os.path.join(tmpdir, "priv.pem")
    pub = os.path.join(tmpdir, "pub.pem")
    r = _run(["openssl", "genpkey", "-algorithm", "Ed25519", "-out", priv])
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    r = _run(["openssl", "pkey", "-in", priv, "-pubout", "-out", pub])
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return priv, pub


def test_install(backend: str) -> None:
    _test_version_file()
    _test_install_sh_truncation_safe()
    _test_install_non_tty()
    _test_mnemonic_word_count()
    _test_mnemonic_paste_normalised()
    _test_recovery_phrase_is_the_only_question()
    _test_balance_reads_in_mirage()
    _test_miraged_banner_hidden_but_errors_kept()
    _test_setup_prompts()
    _test_prompt_answers_reach_env()
    _test_new_install_writes_random_net_tag()
    _test_external_address_rejects_injection()
    _test_forensic_snapshot_refuses_wipe()
    _test_moniker_precedence()
    _test_frontend_env_no_foreign_node()
    _test_launch_wait()
    _test_supervisor_runtime()
    _test_public_cli_help()
    _test_validator_replacement()
    _test_governed_upgrade_prepare()
    _test_backup_restore_contracts()
    _test_status_compact_layout()
    _test_card_amounts_fit()
    _test_cards_are_all_one_height()
    _test_staked_balance_history()
    _test_node_earnings_attribution()
    _test_web_earnings_sources()
    _test_earnings_card()
    _test_retention_building_up()
    _test_catching_up_is_not_a_fault()
    _test_readonly_role_reads_new_indexer_tables()
    _test_param_load_fails_fast_on_denied_grant()
    _test_maintenance_gate_tracks_progress()
    _test_completed_installer_updates()
    _test_resume_refreshes_amended_release()
    _test_partial_chain_reset_preserves_state()
    _test_activation_and_registration_waits()
    _test_pinned_bootstrap_dependencies()
    _test_sshd_validation_survives_socket_activation()
    _test_fresh_deploy_skips_historical_migrations()
    _test_indexer_schema_precedes_migrations()
    _test_indexer_param_refresh_schedule()
    _test_node_temp_cleanup()
    _test_ubuntu_full_upgrade()
    _test_provider_memory_overhead()
    _test_no_swapfile_provisioned()
    _test_disk_floor_matches_live_nodes()
    _test_agree_json_ignores_node_local_state()
    _test_release_workflow_files_tracked()
    _test_docker_context_excludes_private_key()
    _test_pubkey_fingerprint()
    _test_manifest_signatures()
    _test_collision_guard_paginates()
    _test_create_validator_syncing()
    _test_create_validator_gas_price()
    _test_create_validator_min_self_delegation()
    _test_updater_gates()
    _test_releases_are_reachable_from_any_version()
    _test_hosttool_paths()
    _test_updater_hosttools_on_activate_only()
    _test_updater_refreshes_before_activation()
    _test_updater_repairs_uninitialized_node()
    _test_updater_refuses_catching_up()
    _test_host_tools_query_lcd_in_container()
    _test_peer_pull_requires_peer_ahead()
    _test_watermark_never_lowers()
    _test_weekly_restart_skips_catching_up()
    _test_images_pruned_before_every_pull()
    _test_prune_keeps_digest_pinned_images()
    _test_moniker_update_pays_and_verifies()
    _test_stake_floor_and_lock()
    _test_economics_single_source()
    _test_mint_floor_backend_required()
    _test_caddy_well_known()
    _test_unjail_tool()
    _test_stale_chunk_recovery()
    _test_caddy_csp_upgrade_scoped_to_tls()
    _test_repodigest_pin()


def _test_node_temp_cleanup() -> None:
    from deploy.migrations._helpers import cleanup_node_temp_files

    with tempfile.TemporaryDirectory(prefix="node-temp-cleanup-") as tmp:
        config_dir = Path(tmp, ".mirage", "env")
        node_config = Path(tmp, ".mirage", "node", "config")
        config_dir.mkdir(parents=True)
        node_config.mkdir(parents=True)
        temp_file = node_config / "write-file-atomic-123"
        keep_file = node_config / "config.toml"
        temp_file.write_text("partial", encoding="utf-8")
        keep_file.write_text("config", encoding="utf-8")

        cleaned = cleanup_node_temp_files(config_dir)
        if cleaned != 1 or temp_file.exists() or not keep_file.exists():
            _fail(
                "install.migrations.node_temp_cleanup",
                f"cleaned={cleaned} temp_exists={temp_file.exists()} config_exists={keep_file.exists()}",
            )
            return
    _pass("install.migrations.node_temp_cleanup")


def _test_indexer_param_refresh_schedule() -> None:
    import indexer.main as indexer_main

    indexer = object.__new__(indexer_main.Indexer)
    indexer.chain = mock.Mock(grpc_target="127.0.0.1:9090")
    indexer._params_need_post_block_refresh = True
    indexer._catch_up_mode = True
    with (
        mock.patch.object(indexer_main, "load_chain_params") as load,
        mock.patch.object(indexer_main, "get_raw_params", return_value={"mint_floor_split": 0.2}),
    ):
        snapshot, reason = indexer._chain_params_snapshot_for_block(1)
        if snapshot != {"mint_floor_split": 0.2} or reason != "post-start":
            _fail("install.indexer.params_post_start", f"snapshot={snapshot!r} reason={reason!r}")
            return
        load.assert_called_once_with("127.0.0.1:9090", force=True)

        indexer._params_need_post_block_refresh = False
        load.reset_mock()
        snapshot, reason = indexer._chain_params_snapshot_for_block(indexer_main.PARAMS_REFRESH_INTERVAL)
        if snapshot is not None or reason or load.called:
            _fail("install.indexer.params_skip_catchup", f"snapshot={snapshot!r} reason={reason!r}")
            return

        indexer._catch_up_mode = False
        snapshot, reason = indexer._chain_params_snapshot_for_block(indexer_main.PARAMS_REFRESH_INTERVAL)
        if snapshot != {"mint_floor_split": 0.2} or reason != "periodic":
            _fail("install.indexer.params_periodic", f"snapshot={snapshot!r} reason={reason!r}")
            return
    _pass("install.indexer.params_refresh_schedule")


def _test_version_file() -> None:
    raw = Path(VERSION_FILE).read_text(encoding="utf-8")
    value = raw.strip()
    if raw != value + "\n" and raw != value:
        _fail("install.version_one_line", f"VERSION has unexpected padding: {raw!r}")
        return
    if not __import__("re").fullmatch(r"v\d+\.\d+\.\d+", value):
        _fail("install.version_semver", f"VERSION={value!r}")
        return
    binary = os.path.join(REPO_ROOT, "blockchain", "bin", "miraged")
    result = _run([binary, "version", "--long"])
    if result.returncode != 0:
        _fail("install.binary_version_command", result.stderr[-300:])
        return
    reported = next(
        (line.split(":", 1)[1].strip() for line in result.stdout.splitlines() if line.startswith("version:")),
        "",
    )
    if reported.lstrip("v") != value.lstrip("v"):
        _fail("install.binary_version", f"binary={reported!r} VERSION={value!r}")
        return
    _pass("install.version_file", version=value)


def _test_install_sh_truncation_safe() -> None:
    text = Path(INSTALL_SH).read_text(encoding="utf-8")
    if not text.rstrip().endswith('main "$@"'):
        _fail("install.truncation.last_line", 'last line is not main "$@"')
        return
    with tempfile.TemporaryDirectory(prefix="install-trunc-") as tmp:
        truncated = os.path.join(tmp, "install.sh")
        lines = text.splitlines()
        Path(truncated).write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        marker = os.path.join(tmp, "mutated")
        env = {**os.environ, "HOME": tmp}
        r = _run(["bash", truncated], env=env, cwd=tmp)
        if r.returncode != 0:
            _fail("install.truncation.exit", f"truncated script exited {r.returncode}: {r.stderr[-400:]}")
            return
        leftover = [p for p in Path(tmp).rglob("*") if p.is_file() and p.name != "install.sh"]
        if leftover:
            _fail("install.truncation.no_mutation", f"wrote {leftover}")
            return
        if os.path.exists(marker):
            _fail("install.truncation.no_mutation", "marker appeared")
            return
    _pass("install.truncation_safe")


def _test_install_non_tty() -> None:
    env = {**os.environ, "HOME": "/tmp/mirage-install-non-tty-home"}
    r = _run(["bash", INSTALL_SH], env=env, stdin=subprocess.DEVNULL)
    if r.returncode == 0:
        _fail("install.non_tty.exit", "install.sh succeeded without a TTY")
        return
    err = (r.stderr or "") + (r.stdout or "")
    if "TTY" not in err and "interactive" not in err.lower():
        # require_root may fire first if not root; still a named refusal.
        if "must be run as root" not in err:
            _fail("install.non_tty.message", f"unexpected error: {err[-400:]}")
            return
    _pass("install.non_tty_refuses")


def _test_mnemonic_word_count() -> None:
    functions = _install_functions_only()
    script = functions + '\nset_mnemonic "$1"\necho COUNT_OK\n'
    cases = [
        ("eleven words here not twelve at all", 11),
        ("one two three four five six seven eight nine ten eleven twelve thirteen", 13),
        (" ".join(["abandon"] * 24), 24),
    ]
    for phrase, n in cases:
        r = _run(["bash", "-c", script, "_", phrase])
        if r.returncode == 0:
            _fail(f"install.mnemonic.{n}_words", "accepted a non-12-word phrase")
            return
        err = (r.stderr or "") + (r.stdout or "")
        if "12 words" not in err:
            _fail(f"install.mnemonic.{n}_words", f"missing named failure: {err[-300:]}")
            return
        _pass(f"install.mnemonic.rejects_{n}_words")
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    if 'Mnemonic("english")' not in body:
        _fail("install.mnemonic.wordlist", "install.sh does not check the BIP-39 English wordlist")
        return
    if "words not in the BIP-39 English list" not in body:
        _fail("install.mnemonic.invalid_word_message", "missing named failure for unknown BIP-39 words")
        return
    with tempfile.TemporaryDirectory(prefix="mnemonic-literal-") as tmp:
        marker = os.path.join(tmp, "executed")
        payload = f"$(touch${{IFS}}{marker}) " + " ".join(["abandon"] * 11)
        r = _run(["bash", "-c", script, "_", payload])
        if r.returncode != 0 or os.path.exists(marker):
            _fail(
                "install.mnemonic.literal_input",
                f"pasted shell syntax executed={os.path.exists(marker)} rc={r.returncode}",
            )
            return
    if "</dev/tty" not in body:
        _fail("install.mnemonic.tty", "prompt does not read from /dev/tty, so curl | bash cannot work")
        return
    _pass("install.mnemonic.wordlist_named")


def _test_pinned_bootstrap_dependencies() -> None:
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    for variable, relative in (
        ("EXPECTED_VERIFY_SHA256", "deploy/release_verify.py"),
        ("EXPECTED_HARDEN_SHA256", "deploy/harden_server.sh"),
    ):
        match = __import__("re").search(rf'^{variable}="([0-9a-f]{{64}})"$', body, __import__("re").MULTILINE)
        if not match:
            _fail("install.bootstrap.pin_missing", f"{variable} missing")
            return
        actual = __import__("hashlib").sha256(Path(REPO_ROOT, relative).read_bytes()).hexdigest()
        if match.group(1) != actual:
            _fail("install.bootstrap.pin_stale", f"{relative}: pin={match.group(1)} actual={actual}")
            return
    _pass("install.bootstrap.dependencies_pinned")


def _test_fresh_deploy_skips_historical_migrations() -> None:
    """A first install must not point v1.28-era data backfills at an empty database."""
    from deploy.migrations import _has_existing_data

    with tempfile.TemporaryDirectory() as tmp:
        # Everything entrypoint.sh has already created by the time it runs
        # `python3 -m deploy.migrations` on a host that has never started.
        root = Path(tmp, ".mirage")
        env = root / "env"
        env.mkdir(parents=True)
        (root / "postgres").mkdir()
        (root / "postgres" / "PG_VERSION").write_text("16\n", encoding="utf-8")
        (root / "node" / "config").mkdir(parents=True)
        (root / "node" / "config" / "genesis.json").write_text("{}", encoding="utf-8")
        (root / "node" / "data").mkdir()
        (root / "node" / "data" / "priv_validator_state.json").write_text("{}", encoding="utf-8")

        if _has_existing_data(env):
            _fail(
                "install.migrations.fresh_deploy",
                "a fresh install is misread as an existing one, so every historical migration runs",
            )
            return

        # A host that has actually produced blocks must still get its migrations.
        (root / "node" / "data" / "blockstore.db").mkdir()
        if not _has_existing_data(env):
            _fail(
                "install.migrations.existing_deploy",
                "an existing deployment is misread as fresh, so pending migrations would be skipped",
            )
            return
    _pass("install.migrations.fresh_deploy_detection")


def _test_indexer_schema_precedes_migrations() -> None:
    entrypoint = Path(REPO_ROOT, "deploy", "entrypoint.sh").read_text(encoding="utf-8")
    schema_at = entrypoint.find("from indexer.database import DatabaseManager")
    migrate_at = entrypoint.find("python3 -m deploy.migrations")
    if schema_at < 0:
        _fail(
            "install.migrations.indexer_schema",
            "entrypoint.sh never creates the indexer schema, so data migrations hit missing tables",
        )
        return
    if migrate_at < 0 or schema_at > migrate_at:
        _fail("install.migrations.indexer_schema_order", "indexer schema is created after migrations run")
        return
    _pass("install.migrations.indexer_schema_first")


def _test_sshd_validation_survives_socket_activation() -> None:
    harden = Path(REPO_ROOT, "deploy", "harden_server.sh").read_text(encoding="utf-8")
    step = harden.partition("# Step 4")[2].partition("# Step 5")[0]
    code = [line.strip() for line in step.splitlines() if not line.lstrip().startswith("#")]
    mkdir_at = next((i for i, line in enumerate(code) if line == "install -d -m 0755 /run/sshd"), None)
    test_at = next((i for i, line in enumerate(code) if line == "sshd -t"), None)
    if mkdir_at is None:
        _fail(
            "install.sshd.privsep_dir",
            "sshd -t runs without /run/sshd, which fatals on a socket-activated host",
        )
        return
    if test_at is None or mkdir_at > test_at:
        _fail("install.sshd.privsep_order", "/run/sshd is created after sshd -t has already run")
        return
    if "ssh.socket" not in step:
        _fail("install.sshd.reload_target", "reload assumes a long-running ssh.service")
        return
    _pass("install.sshd.socket_activation")


def _test_ubuntu_full_upgrade() -> None:
    harden = Path(REPO_ROOT, "deploy", "harden_server.sh").read_text(encoding="utf-8")
    step_one = harden.partition("# Step 1")[2].partition("# Step 2")[0]
    if "apt-get -qq update" not in step_one or "full-upgrade" not in step_one:
        _fail("install.ubuntu.initial_upgrade", "initial hardening does not update and fully upgrade Ubuntu")
        return
    if "DEBIAN_FRONTEND=noninteractive" not in step_one or "NEEDRESTART_MODE=a" not in step_one:
        _fail("install.ubuntu.noninteractive_upgrade", "initial Ubuntu upgrade can prompt for input")
        return

    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    if 'bash "$script" --no-reboot' not in install or install.count("/var/run/reboot-required") < 2:
        _fail("install.ubuntu.reboot_resume", "installer does not stop and resume safely after an Ubuntu upgrade")
        return
    _pass("install.ubuntu.full_upgrade")


def _test_provider_memory_overhead() -> None:
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    if "mem_mib < 3800" not in install:
        _fail("install.memory.minimum", "installer does not accept normal overhead on a 4 GB cloud VM")
        return
    if "mem_mib < 7600" in install:
        _fail("install.memory.recommended", "installer still warns for 8 GB, which no live validator uses")
        return
    if "at least 3800 MiB visible after provider overhead" not in install:
        _fail("install.memory.message", "memory rejection does not explain provider overhead")
        return
    _pass("install.memory.provider_overhead")


def _test_no_swapfile_provisioned() -> None:
    """v1.36.6: the swapfile was measured to absorb nothing and is no longer created.

    It was originally justified by a memory-pressure theory of the 2026-06-16
    divergence that the postmortem refuted.
    """
    harden = Path(REPO_ROOT, "deploy", "harden_server.sh").read_text(encoding="utf-8")
    for stale in ("fallocate -l 2G", "mkswap", "swapon /swapfile", "none swap sw"):
        if stale in harden:
            _fail("install.swap.still_created", f"hardening still provisions swap: {stale}")
            return
    # set -euo pipefail is active, and `swapon --show` exits non-zero with no swap.
    if "swapon --show" in harden:
        _fail("install.swap.verification", "verification runs swapon --show on a swapless host")
        return
    if "vm.swappiness = 10" not in harden:
        _fail("install.swap.swappiness", "hosts that still carry an old /swapfile lost their swappiness bias")
        return
    _pass("install.swap.not_provisioned")


def _test_disk_floor_matches_live_nodes() -> None:
    """A validator's whole footprint is ~15 GiB, so the floor must fit a 25 GB disk."""
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    if "disk_gib < 20" not in install:
        _fail("install.disk.floor", "disk floor does not match the ~15 GiB a live validator occupies")
        return
    if "disk_gib < 40" not in install:
        _fail("install.disk.headroom", "installer does not warn about growth headroom")
        return
    for stale in ("80 * 1024 * 1024 * 1024", "at least 80 GiB free"):
        if stale in install:
            _fail("install.disk.stale_floor", f"installer still demands an unreachable disk floor: {stale}")
            return
    _pass("install.disk.floor_matches_live_nodes")


def _test_agree_json_ignores_node_local_state() -> None:
    """The cross-endpoint check may only compare chain-derived fields.

    get_profile also reports each node's own backend state, so comparing whole
    documents rejected every real account: mirage.talk answered
    new_inbox_items 119 where the second endpoint answered 0.
    """
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    if 'agree_json "$api" "/api/get_profile?address=${ADDRESS}" "username"' not in install:
        _fail("install.agree_json.caller", "the profile preflight does not narrow the comparison to username")
        return

    def serve(body):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, fmt, *args):
                return

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    function = _shell_function(INSTALL_SH, "agree_json")
    servers = [
        serve({"username": "alice", "new_inbox_items": 119}),
        serve({"username": "alice", "new_inbox_items": 0}),
        serve({"username": "bob", "new_inbox_items": 0}),
    ]

    def call(hosts, keys):
        urls = ",".join(f"http://127.0.0.1:{h.server_address[1]}" for h in hosts)
        script = f"set -euo pipefail\n{function}\nagree_json {urls!r} /api/get_profile?address=x {keys!r}"
        return _run(["bash", "-c", script], timeout=30)

    try:
        agreeing, differing_inbox, differing_username = servers
        r = call([agreeing, differing_inbox], "username")
        if r.returncode != 0:
            _fail(
                "install.agree_json.node_local", f"inbox counts still block the install: rc={r.returncode} {r.stderr}"
            )
            return
        if json.loads(r.stdout).get("username") != "alice":
            _fail("install.agree_json.body", f"the full first body is no longer returned: {r.stdout}")
            return
        r = call([agreeing, differing_inbox], "")
        if r.returncode == 0:
            _fail("install.agree_json.unprojected", "an unnarrowed comparison is no longer strict")
            return
        r = call([agreeing, differing_username], "username")
        if r.returncode == 0 or "endpoints disagree" not in r.stderr:
            _fail("install.agree_json.conflict", f"a contradicted username passed: rc={r.returncode} {r.stderr}")
            return
        _pass("install.agree_json.compares_chain_fields_only")
    finally:
        for httpd in servers:
            httpd.shutdown()


def _test_mnemonic_paste_normalised() -> None:
    """A pasted phrase must survive what terminals and password managers add.

    A no-break space counted as one word and a bracketed-paste marker attached
    itself to the first and last word, so a correct phrase was rejected.
    """
    functions = _install_functions_only()
    phrase = " ".join(["abandon"] * 11 + ["about"])
    script = functions + '\nset_mnemonic "$1"\nprintf %s "$MNEMONIC"\n'
    variants = {
        "double_spaces": phrase.replace(" ", "   "),
        "leading_trailing": f"   {phrase}  ",
        "tabs": phrase.replace(" ", "\t"),
        "no_break_space": phrase.replace(" ", "\u00a0"),
        "narrow_no_break_space": phrase.replace(" ", "\u202f"),
        "ideographic_space": phrase.replace(" ", "\u3000"),
        "zero_width_space": phrase.replace(" ", " \u200b"),
        "byte_order_mark": f"\ufeff{phrase}",
        "bracketed_paste": f"\x1b[200~{phrase}\x1b[201~",
        "trailing_carriage_return": f"{phrase}\r",
        "capitalised": phrase.title(),
    }
    for name, raw in variants.items():
        r = _run(["bash", "-c", script, "_", raw])
        if r.returncode != 0:
            _fail(f"install.mnemonic.paste.{name}", f"rejected a correct phrase: {(r.stderr or r.stdout)[-200:]}")
            return
        if r.stdout != phrase:
            _fail(f"install.mnemonic.paste.{name}", f"normalised to {r.stdout!r}, expected {phrase!r}")
            return

    # Normalising whitespace must not turn a wrong word count into a right one.
    for raw, count in ((phrase.replace(" ", "\u00a0", 1) + "\u00a0extra", 13), ("\u00a0".join(["abandon"] * 11), 11)):
        r = _run(["bash", "-c", script, "_", raw])
        if r.returncode == 0 or "12 words" not in (r.stderr or "") + (r.stdout or ""):
            _fail("install.mnemonic.paste.count", f"accepted a {count}-word phrase after normalising")
            return
    if "separated by spaces" not in Path(INSTALL_SH).read_text(encoding="utf-8"):
        _fail("install.mnemonic.paste.guidance", "the phrase prompt does not say the words need spaces between them")
        return
    _pass(f"install.mnemonic.normalises_{len(variants)}_paste_shapes")


def _test_recovery_phrase_is_the_only_question() -> None:
    """An install asks for the phrase and nothing else, and says what it decided."""
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    reads = re.findall(r"^.*read .*/dev/tty.*$", body, re.M)
    if len(reads) != 2:
        _fail("install.prompts.only_the_phrase", f"unexpected interactive reads: {reads}")
        return
    if not any("Recovery phrase" in r for r in reads):
        _fail("install.prompts.only_the_phrase", f"missing recovery-phrase read: {reads}")
        return
    if not any("read -r confirm" in r for r in reads):
        _fail("install.prompts.only_the_phrase", f"missing replacement confirmation read: {reads}")
        return

    # No MIRAGE_* variables: the defaults path must not block and must report.
    env = {k: v for k, v in os.environ.items() if not k.startswith("MIRAGE_")}
    script = _install_functions_only() + "\nUSERNAME=Anon-FuckWard\nPUBLIC_IP=203.0.113.7\nchoose_settings\n"
    r = _run(["bash", "-c", script], env=env, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        _fail("install.prompts.defaults_run", f"rc={r.returncode} err={(r.stderr or '')[-300:]}")
        return
    expected = (
        "\n"
        "==> Validator name: Anon-FuckWard\n"
        "\n"
        "==> Media uploads enabled: false\n"
        "\n"
        "\n"
        "No domain for now; this node will serve on its IP. You can set it up later using "
        "`mirage-domain --set example.com`, which will enable SSL (https) for you and bind the domain.\n"
    )
    if r.stdout != expected:
        _fail("install.prompts.default_report", f"got {r.stdout!r}")
        return
    _pass("install.prompts.only_the_phrase")


def _test_balance_reads_in_mirage() -> None:
    """umirage is an implementation detail; an operator is shown grouped Mirage."""
    script = _install_functions_only() + '\nas_mirage "$1"\n'
    for amount, want in (
        ("15000000000000", "15,000,000"),
        ("1000000", "1"),
        ("999000000", "999"),
        ("1000000000", "1,000"),
        ("0", "0"),
    ):
        r = _run(["bash", "-c", script, "_", amount])
        if r.returncode != 0 or r.stdout != want:
            _fail("install.balance.mirage_units", f"{amount} -> {r.stdout!r} (want {want!r})")
            return
    # The denom still appears in the REST query and the manifest field name; what
    # must not appear is a umirage figure in something the operator reads.
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    printed = [line for line in body.splitlines() if re.match(r"\s*(echo|printf|die)\b", line) and "umirage" in line]
    if printed:
        _fail("install.balance.raw_denom", f"raw umirage shown to the operator: {printed}")
        return
    _pass("install.balance.mirage_units")


def _test_miraged_banner_hidden_but_errors_kept() -> None:
    """The registration banner must not reach the transcript, and errors still must."""
    script = (
        _install_functions_only()
        + """
quiet_run bash -c 'echo "core/types: registered msg interfaces" >&2; echo ok'
echo "rc=$?"
quiet_run bash -c 'echo "the real failure" >&2; exit 3' || echo "rc=$?"
"""
    )
    r = _run(["bash", "-c", script])
    if "core/types" in r.stderr:
        _fail("install.banner.suppressed", "the miraged banner still reaches stderr on success")
        return
    if "ok" not in r.stdout or "rc=0" not in r.stdout:
        _fail("install.banner.stdout_passthrough", f"stdout={r.stdout!r}")
        return
    if "the real failure" not in r.stderr or "rc=3" not in r.stdout:
        _fail("install.banner.errors_kept", f"out={r.stdout!r} err={r.stderr!r}")
        return
    _pass("install.banner.hidden_errors_kept")


def _test_setup_prompts() -> None:
    """The install-time questions must answer themselves from the environment.

    Every prompt takes a variable so an unattended run never blocks, and a
    variable that is set but empty is a real answer: it is how an operator says
    "no domain" without being asked.
    """
    functions = _install_functions_only()
    script = (
        functions
        + "\nUSERNAME=alice\nPUBLIC_IP=203.0.113.7\n"
        + "choose_settings >/dev/null\n"
        + 'printf "%s|%s|%s" "$MONIKER_CHOICE" "$DOMAIN_ARG" "$MEDIA_UPLOADS"\n'
    )

    def run_env(**env) -> subprocess.CompletedProcess:
        return _run(["bash", "-c", script], env={**os.environ, **env})

    # Only a domain can reach DNS, and a test must not depend on resolving one,
    # so the accepted-domain cases use a name that cannot resolve anywhere.
    cases = {
        "defaults": (
            {"MIRAGE_MONIKER": "", "MIRAGE_DOMAIN": "", "MIRAGE_MEDIA_UPLOADS": ""},
            "alice||false",
        ),
        "all_answered": (
            {
                "MIRAGE_MONIKER": "my-validator",
                "MIRAGE_DOMAIN": "node.invalid",
                "MIRAGE_MEDIA_UPLOADS": "yes",
            },
            "my-validator|node.invalid|true",
        ),
        "whitespace_trimmed": (
            {"MIRAGE_MONIKER": "  spaced name  ", "MIRAGE_DOMAIN": " node.invalid ", "MIRAGE_MEDIA_UPLOADS": " no "},
            "spaced name|node.invalid|false",
        ),
    }
    for name, (env, expected) in cases.items():
        r = run_env(**env)
        if r.returncode != 0:
            _fail(f"install.prompts.{name}", f"rc={r.returncode} err={(r.stderr or '')[-200:]}")
            return
        if r.stdout != expected:
            _fail(f"install.prompts.{name}", f"got {r.stdout!r}, expected {expected!r}")
            return

    rejected = {
        "name_too_long": {"MIRAGE_MONIKER": "x" * 71, "MIRAGE_DOMAIN": "", "MIRAGE_MEDIA_UPLOADS": ""},
        "name_with_control_char": {"MIRAGE_MONIKER": "bad\tname", "MIRAGE_DOMAIN": "", "MIRAGE_MEDIA_UPLOADS": ""},
        "domain_not_hostname": {"MIRAGE_MONIKER": "", "MIRAGE_DOMAIN": "http://x.example", "MIRAGE_MEDIA_UPLOADS": ""},
        "media_not_yes_or_no": {"MIRAGE_MONIKER": "", "MIRAGE_DOMAIN": "", "MIRAGE_MEDIA_UPLOADS": "maybe"},
    }
    for name, env in rejected.items():
        r = run_env(**env)
        if r.returncode == 0:
            _fail(f"install.prompts.{name}", f"accepted a bad answer: {r.stdout!r}")
            return
        if "ERROR" not in (r.stderr or ""):
            _fail(f"install.prompts.{name}", f"failed without naming the problem: {(r.stderr or '')[-200:]}")
            return

    # A name is asked for before anything slow runs, and never again on a resume.
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    if not re.search(r"if ! state_at_least configured; then\n\s+choose_settings\n\s+configure\n", body):
        _fail("install.prompts.placement", "prompts do not run once, immediately before configure")
        return
    _pass(f"install.prompts.answerable_from_env_{len(cases) + len(rejected)}_cases")


def _test_prompt_answers_reach_env() -> None:
    """The answers have to land in the file the reader of each key looks at.

    MEDIA_UPLOADS_ENABLED is read from backend.env while everything else the
    installer writes lives in node.env, so a writer hardwired to one file would
    silently drop the answer.
    """
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    expected = {
        "MONIKER": ('write_env_key MONIKER "$MONIKER_CHOICE"', "node.env"),
        "WATCHDOG_AUTORECOVER": ("write_env_key WATCHDOG_AUTORECOVER true", "node.env"),
        "MEDIA_UPLOADS_ENABLED": (
            'write_env_key MEDIA_UPLOADS_ENABLED "$MEDIA_UPLOADS" /root/.mirage/env/backend.env',
            "backend.env",
        ),
        "NET_TAG_HMAC_KEY": (
            "write_env_key NET_TAG_HMAC_KEY \"$(python3 -c 'import secrets; print(secrets.token_hex(32))')\" /root/.mirage/env/backend.env",
            "backend.env",
        ),
    }
    for key, (line, _dest) in expected.items():
        if line not in body:
            _fail(f"install.env_write.{key}", f"configure does not write {key} as expected")
            return
    if 'write_env_key MONIKER "$USERNAME"' in body:
        _fail("install.env_write.moniker_ignored", "configure still writes the username over the operator's answer")
        return

    # Exercise the writer itself: it must honour an explicit destination, keep
    # the file at 0600, and replace a key in place rather than duplicating it.
    lines = body.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "write_env_key() {")
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.strip() == "}")
    writer = "\n".join(line[2:] if line.startswith("  ") else line for line in lines[start : end + 1])
    with tempfile.TemporaryDirectory(prefix="env-write-") as tmp:
        node_env = os.path.join(tmp, "node.env")
        backend_env = os.path.join(tmp, "backend.env")
        Path(node_env).write_text("MONIKER=validator\nWATCHDOG_AUTORECOVER=false\n", encoding="utf-8")
        Path(backend_env).write_text("MEDIA_UPLOADS_ENABLED=false\n", encoding="utf-8")
        script = (
            "set -euo pipefail\n"
            + writer.replace("/root/.mirage/env/node.env", node_env)
            + f'\nwrite_env_key MONIKER "chosen name"\n'
            + "write_env_key WATCHDOG_AUTORECOVER true\n"
            + f"write_env_key MEDIA_UPLOADS_ENABLED true {backend_env}\n"
        )
        r = _run(["bash", "-c", script])
        if r.returncode != 0:
            _fail("install.env_write.runs", f"rc={r.returncode} err={(r.stderr or '')[-200:]}")
            return
        node_text = Path(node_env).read_text(encoding="utf-8")
        backend_text = Path(backend_env).read_text(encoding="utf-8")
        if node_text != "MONIKER='chosen name'\nWATCHDOG_AUTORECOVER=true\n":
            _fail("install.env_write.node_env", f"node.env is {node_text!r}")
            return
        if backend_text != "MEDIA_UPLOADS_ENABLED=true\n":
            _fail("install.env_write.backend_env", f"backend.env is {backend_text!r}")
            return
        pwn = os.path.join(tmp, "pwned")
        payload = os.path.join(tmp, "payload.env")
        Path(payload).write_text("MONIKER=validator\n", encoding="utf-8")
        payload_script = (
            "set -euo pipefail\n"
            + writer.replace("/root/.mirage/env/node.env", payload)
            + f"\nwrite_env_key MONIKER 'x$(touch {pwn})'\n"
        )
        r = _run(["bash", "-c", payload_script])
        if r.returncode != 0:
            _fail("install.env_write.payload_runs", f"rc={r.returncode} err={(r.stderr or '')[-200:]}")
            return
        want = f"x$(touch {pwn})"
        sourced = _run(["bash", "-ce", 'set -a; . "$1"; set +a; printf %s "$MONIKER"', "bash", payload])
        if sourced.returncode != 0:
            _fail("install.env_write.quoted_source", f"src_rc={sourced.returncode} err={sourced.stderr!r}")
            return
        if os.path.exists(pwn):
            _fail("install.env_write.quoted_source_exec", "bash-sourcing the quoted MONIKER still executed")
            return
        if sourced.stdout != want:
            _fail("install.env_write.quoted_literal", f"MONIKER became {sourced.stdout!r}")
            return
        loader = os.path.join(REPO_ROOT, "deploy", "load_env_exports.py")
        loaded = _run(["bash", "-ce", 'eval "$(python3 "$1" "$2")"; printf %s "$MONIKER"', "bash", loader, payload])
        if loaded.returncode != 0 or loaded.stdout != want or os.path.exists(pwn):
            _fail(
                "install.env_write.loader_literal",
                f"rc={loaded.returncode} out={loaded.stdout!r} err={loaded.stderr!r} pwn={os.path.exists(pwn)}",
            )
            return
        missing = _run(["python3", loader, os.path.join(tmp, "no-such.env")])
        if missing.returncode == 0 or "does not exist" not in missing.stderr:
            _fail("install.env_write.loader_missing", f"rc={missing.returncode} err={missing.stderr!r}")
            return
        bad_quote = os.path.join(tmp, "bad-quote.env")
        Path(bad_quote).write_text("MONIKER='unterminated\n", encoding="utf-8")
        quoted = _run(["python3", loader, bad_quote])
        if quoted.returncode == 0 or "not parseable" not in quoted.stderr:
            _fail("install.env_write.loader_bad_quote", f"rc={quoted.returncode} err={quoted.stderr!r}")
            return
        for path in (node_env, backend_env):
            mode = os.stat(path).st_mode & 0o777
            if mode != 0o600:
                _fail("install.env_write.mode", f"{os.path.basename(path)} left at {oct(mode)}")
                return
    _pass("install.env_write.answers_reach_their_own_files")


def _test_new_install_writes_random_net_tag() -> None:
    """A first install writes a random HMAC key; a filled key is left alone."""
    from deploy.migrations import ALWAYS_RUN_KEYS

    if "v1.36.1-ensure-net-tag-key" in ALWAYS_RUN_KEYS:
        _fail(
            "install.net_tag.not_a_skipped_migration",
            "NET_TAG_HMAC_KEY must be written at install, not by a fresh-host-skipped migration",
        )
        return
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    if (
        "secrets.token_hex(32)" not in body
        or "NET_TAG_HMAC_KEY" not in body.split("configure()")[1].split("identity()")[0]
    ):
        _fail("install.net_tag.configure_writes_key", "configure() does not generate NET_TAG_HMAC_KEY")
        return
    lines = body.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "write_env_key() {")
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line.strip() == "}")
    writer = "\n".join(line[2:] if line.startswith("  ") else line for line in lines[start : end + 1])
    with tempfile.TemporaryDirectory(prefix="net-tag-") as tmp:
        backend_env = os.path.join(tmp, "backend.env")
        Path(backend_env).write_text("NET_TAG_HMAC_KEY=\n", encoding="utf-8")
        script = f"""
set -euo pipefail
{writer}
if ! python3 - {backend_env!r} <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
matches = re.findall(r"^NET_TAG_HMAC_KEY=(.*)$", text, re.M)
if len(matches) > 1:
    raise SystemExit(f"duplicate NET_TAG_HMAC_KEY entries in {{sys.argv[1]}}")
val = matches[0].strip().strip("\\"\\'") if matches else ""
raise SystemExit(0 if val else 1)
PY
then
  write_env_key NET_TAG_HMAC_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" {backend_env!r}
fi
"""
        first = _run(["bash", "-c", script])
        if first.returncode != 0:
            _fail("install.net_tag.generate", f"rc={first.returncode} err={first.stderr}")
            return
        generated = re.search(r"^NET_TAG_HMAC_KEY=(.*)$", Path(backend_env).read_text(encoding="utf-8"), re.M)
        raw = generated.group(1).strip().strip("'\"") if generated else ""
        if not re.fullmatch(r"[0-9a-f]{64}", raw):
            _fail("install.net_tag.hex", f"generated {raw!r}")
            return
        second = _run(["bash", "-c", script])
        if second.returncode != 0:
            _fail("install.net_tag.preserve_runs", f"rc={second.returncode} err={second.stderr}")
            return
        again = re.search(r"^NET_TAG_HMAC_KEY=(.*)$", Path(backend_env).read_text(encoding="utf-8"), re.M)
        kept = again.group(1).strip().strip("'\"") if again else ""
        if kept != raw:
            _fail("install.net_tag.rotated", f"first={raw} second={kept}")
            return
    _pass("install.net_tag.random_on_new_install")


def _test_external_address_rejects_injection() -> None:
    fns = _install_functions_only()
    bad = "tcp://1.2.3.4:26656; touch /tmp/pwned"
    r = _run(["bash", "-c", fns + f"MIRAGE_EXTERNAL_ADDRESS={bad!r}\nexternal_address\n"])
    if r.returncode == 0:
        _fail("install.external_address.accepts_injection", r.stdout[-200:])
        return
    if "tcp://IPv4:port" not in r.stderr:
        _fail("install.external_address.message", r.stderr[-200:])
        return
    ok = _run(["bash", "-c", fns + "MIRAGE_EXTERNAL_ADDRESS=tcp://203.0.113.9:26656\nexternal_address\n"])
    if ok.returncode != 0 or ok.stdout.strip() != "tcp://203.0.113.9:26656":
        _fail("install.external_address.valid", f"rc={ok.returncode} out={ok.stdout!r} err={ok.stderr[-200:]}")
        return
    _pass("install.external_address.rejects_injection")


def _test_forensic_snapshot_refuses_wipe() -> None:
    """mkdir failure in snapshot_diverged_state must not reach wipe_chain_dbs."""
    recover = Path(os.path.join(REPO_ROOT, "scripts", "recover.sh")).read_text(encoding="utf-8")
    if 'mkdir -p "$cap" || { log "WARNING:' in recover:
        _fail("recover.forensic.mkdir_fail_open", "snapshot still returns 0 when mkdir fails")
        return
    if "refusing to wipe chain DBs" not in recover:
        _fail("recover.forensic.refuse_wipe", "snapshot no longer dies before wipe")
        return
    with tempfile.TemporaryDirectory(prefix="forensic-") as tmp:
        node_home = os.path.join(tmp, "node")
        data = os.path.join(node_home, "data")
        os.makedirs(os.path.join(data, "application.db"))
        Path(os.path.join(data, "application.db", "x")).write_text("state", encoding="utf-8")
        blocked = os.path.join(tmp, "blocked")
        Path(blocked).write_text("not-a-directory\n", encoding="utf-8")
        script = f"""
set -euo pipefail
NODE_HOME={node_home!r}
FORENSIC_ROOT={blocked!r}
LOCAL_DIVERGED_HEIGHT=1
log() {{ printf '%s\\n' "$*" >&2; }}
die() {{ log "ERROR: $*"; exit 1; }}
prune_forensic_captures() {{ return 0; }}
"""
        # Pull the two functions from recover.sh by name.
        for name in ("snapshot_diverged_state", "wipe_chain_dbs"):
            script += _shell_function(os.path.join(REPO_ROOT, "scripts", "recover.sh"), name)
        script += "wipe_chain_dbs\n"
        r = _run(["bash", "-c", script])
        if r.returncode == 0:
            _fail("recover.forensic.wipe_ran", f"wipe succeeded without a snapshot: {r.stderr[-200:]}")
            return
        if "refusing to wipe" not in r.stderr:
            _fail("recover.forensic.wipe_message", r.stderr[-300:])
            return
        if not os.path.isdir(os.path.join(data, "application.db")):
            _fail("recover.forensic.db_deleted", "live application.db was removed after a failed snapshot")
            return
    _pass("recover.forensic.snapshot_failure_aborts_wipe")


def _test_moniker_precedence() -> None:
    """A chosen name must survive a domain being set.

    init.sh used to overwrite MONIKER with https://DOMAIN whenever a domain was
    configured, which silently discarded the name the installer asks for and
    then registers on-chain. The site URL is now only the unnamed default, so
    the existing public nodes keep the name they already render.
    """
    init_sh = os.path.join(REPO_ROOT, "deploy", "init.sh")
    lines = Path(init_sh).read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith('if [ -z "${MONIKER:-}" ]'))
        end = next(i for i, line in enumerate(lines[start:], start) if line == 'MONIKER="${MONIKER:-validator}"')
    except StopIteration:
        _fail("install.moniker.block", "init.sh no longer derives MONIKER in a recognisable block")
        return
    snippet = "\n".join(lines[start : end + 1]) + '\nprintf %s "$MONIKER"\n'
    cases = {
        ("chosen", "example.com"): "chosen",
        ("", "example.com"): "https://example.com",
        ("", ""): "validator",
        ("mirage-node", "mirage.talk"): "mirage-node",
    }
    for (moniker, domain), expected in cases.items():
        r = _run(["bash", "-c", snippet], env={**os.environ, "MONIKER": moniker, "DOMAIN": domain})
        if r.returncode != 0:
            _fail("install.moniker.runs", f"rc={r.returncode} err={(r.stderr or '')[-200:]}")
            return
        if r.stdout != expected:
            _fail(
                f"install.moniker.{moniker or 'unset'}_{domain or 'no_domain'}",
                f"got {r.stdout!r}, expected {expected!r}",
            )
            return
    _pass(f"install.moniker.operator_choice_wins_{len(cases)}_cases")


def _test_frontend_env_no_foreign_node() -> None:
    """A fresh operator's config must not point at somebody else's node.

    The bundle is built with VITE_API_BASE=/api, so a URL in the template never
    took effect; it only told an operator their node talks to another one.
    """
    template = os.path.join(REPO_ROOT, "deploy", "templates", "env", "frontend.env")
    values = dict(
        line.split("=", 1)
        for line in Path(template).read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    if "VITE_API_BASE" not in values:
        _fail("install.frontend_env.present", "VITE_API_BASE is gone from the template")
        return
    if values["VITE_API_BASE"].strip():
        _fail("install.frontend_env.foreign_node", f"template ships VITE_API_BASE={values['VITE_API_BASE']!r}")
        return
    dockerfile = Path(os.path.join(REPO_ROOT, "deploy", "Dockerfile")).read_text(encoding="utf-8")
    if "VITE_API_BASE=/api" not in dockerfile:
        _fail("install.frontend_env.build_arg", "the image no longer builds the bundle against /api")
        return
    _pass("install.frontend_env.defaults_to_this_node")


def _test_launch_wait() -> None:
    """The startup wait must outlast a first boot but end the moment it crashes.

    A flat 120s deadline failed a real install: restarts reach RPC in ~35s, but
    a first boot also creates the Postgres cluster and migrates empty databases.
    """
    functions = _install_functions_only()
    with tempfile.TemporaryDirectory(prefix="launch-wait-") as tmp:
        launch_stub = os.path.join(tmp, "mirage-launch")
        launched = os.path.join(tmp, "launched")
        Path(launch_stub).write_text(f"#!/bin/bash\necho called >> {launched}\n", encoding="utf-8")
        os.chmod(launch_stub, 0o755)
        polls = os.path.join(tmp, "polls")

        def script(running: str, restarting: str, restarts: str, container_image: str, rpc_after: int) -> str:
            return (
                functions.replace("/usr/local/bin/mirage-launch", launch_stub)
                + f"""
IMAGE=pinned-image
USERNAME=alice
sleep() {{ :; }}
curl() {{
  local n=0
  [[ -f {polls!r} ]] && n=$(<{polls!r})
  n=$((n + 1)); echo "$n" > {polls!r}
  (( n > {rpc_after} ))
}}
docker() {{
  case "$*" in
    *"{{{{.State.Running}}}}"*) echo {running} ;;
    *"{{{{.State.Restarting}}}}"*) echo {restarting} ;;
    *"{{{{.RestartCount}}}}"*) {restarts} ;;
    *"{{{{.Id}}}}"*) echo sha256:pinned ;;
    *"{{{{.Image}}}}"*) echo {container_image} ;;
    logs*) echo "stub: applying deploy migrations" ;;
    *) echo "unexpected docker $*" >&2; return 1 ;;
  esac
}}
launch
"""
            )

        # A node already up on the pinned image must not be recreated.
        r = _run(["bash", "-c", script("true", "false", "echo 0", "sha256:pinned", 2)])
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0 or "already running the pinned image" not in out or "RPC is up" not in out:
            _fail("install.launch.resume", f"rc={r.returncode} out={out[-300:]}")
            return
        if os.path.exists(launched):
            _fail("install.launch.resume_recreated", "recreated a container that was already serving")
            return

        # A different image must be launched, then waited for.
        Path(polls).unlink(missing_ok=True)
        r = _run(["bash", "-c", script("true", "false", "echo 0", "sha256:other", 1)])
        if r.returncode != 0 or not os.path.exists(launched):
            _fail("install.launch.starts_container", f"rc={r.returncode} err={(r.stderr or '')[-300:]}")
            return

        # A container that died must fail immediately, showing its own output.
        Path(polls).unlink(missing_ok=True)
        r = _run(["bash", "-c", script("false", "false", "echo 0", "sha256:pinned", 10**9)])
        err = r.stderr or ""
        if r.returncode == 0 or "no longer running" not in err or "applying deploy migrations" not in err:
            _fail("install.launch.dead_container", f"rc={r.returncode} err={err[-300:]}")
            return

        # A crash loop must be named as one rather than waiting out the deadline.
        Path(polls).unlink(missing_ok=True)
        counter = os.path.join(tmp, "restarts")
        Path(counter).write_text("0", encoding="utf-8")
        bump = f'n=$(<{counter!r}); echo $((n + 1)) > {counter!r}; echo "$n"'
        r = _run(["bash", "-c", script("true", "false", bump, "sha256:pinned", 10**9)])
        if r.returncode == 0 or "restarting in a loop" not in (r.stderr or ""):
            _fail("install.launch.crash_loop", f"rc={r.returncode} err={(r.stderr or '')[-300:]}")
            return

    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    if "budget=900" not in body:
        _fail("install.launch.budget", "the startup budget is not the measured-and-padded 900s")
        return
    if "RPC did not become ready in 120s" in body:
        _fail("install.launch.stale_budget", "the 120s deadline that failed a real first boot is still present")
        return
    if "last 40 lines of miraged output" not in body or "/root/.mirage/logs/node/miraged-*.log" not in body:
        _fail("install.launch.node_log", "startup failure still hides the supervised miraged error")
        return
    _pass("install.launch.waits_for_first_boot_and_fails_fast_on_crash")


def _test_supervisor_runtime() -> None:
    """PID 1 is Supervisor; mirage-status is the operator interface."""
    entrypoint = Path(os.path.join(REPO_ROOT, "deploy", "entrypoint.sh")).read_text(encoding="utf-8")
    dockerfile = Path(os.path.join(REPO_ROOT, "deploy", "Dockerfile")).read_text(encoding="utf-8")
    installer = Path(INSTALL_SH).read_text(encoding="utf-8")
    dashboard = Path(os.path.join(REPO_ROOT, "scripts", "status_dashboard.py")).read_text(encoding="utf-8")
    status_tool = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-status")).read_text(encoding="utf-8")
    if "tmux" in entrypoint:
        _fail("install.supervisor.entrypoint_tmux", "entrypoint.sh still contains tmux")
        return
    if "exec supervisord -n" not in entrypoint:
        _fail("install.supervisor.pid1", "entrypoint.sh must exec supervisord as PID 1")
        return
    if "run_miraged_supervised.sh" not in entrypoint or "run_indexer_supervised.sh" not in entrypoint:
        _fail("install.supervisor.wrappers", "entrypoint must still name the supervised wrappers")
        return
    if "python3 indexer/main.py" in entrypoint:
        _fail("install.supervisor.unsupervised_indexer", "entrypoint must not launch the indexer unsupervised")
        return
    if "supervisor \\" not in dockerfile:
        _fail("install.supervisor.image_pkg", "Dockerfile must install supervisor")
        return
    runtime = (
        dockerfile[dockerfile.find("Install runtime dependencies") :]
        if "Install runtime dependencies" in dockerfile
        else dockerfile
    )
    if "tmux" in runtime:
        _fail("install.supervisor.image_tmux", "runtime image still installs tmux")
        return
    if "HEALTHCHECK" not in dockerfile:
        _fail("install.supervisor.healthcheck", "Dockerfile must define a HEALTHCHECK")
        return
    if "get_tmux_visibility_state" in dashboard or "SIGUSR1" in dashboard:
        _fail("install.supervisor.dashboard_tmux", "status dashboard still has tmux/SIGUSR1 behavior")
        return
    if "render_compact_dashboard" not in dashboard or "term_width < 100" not in dashboard:
        _fail("install.supervisor.compact", "dashboard must compact-render 80x24 terminals")
        return
    if "docker exec -it" not in status_tool or "--interval" not in status_tool:
        _fail("install.supervisor.status_tty", "mirage-status must allocate a TTY for live mode")
        return
    if "from deploy.bootstrap_join import TRUST_LOOKBACK" not in installer:
        _fail("install.supervisor.sync_target", "installer sync target can drift from bootstrap trust derivation")
        return
    if "Type exactly 'replace'" not in installer or "apply_replacement_watermark" not in installer:
        _fail("install.supervisor.replace", "installer is missing the seed-only replacement path")
        return

    script = (
        _install_functions_only()
        + """
sync_summary() { echo 'waiting for state-sync snapshot near block 2,100,000 (0%)'; }
PUBLIC_IP=203.0.113.7
USERNAME=Amsterdam-Node
ADDRESS=mirage1test
print_next_steps
"""
    )
    result = _run(["bash", "-c", script])
    output = result.stdout or ""
    if (
        result.returncode != 0
        or "Sync:      waiting for state-sync snapshot" not in output
        or "Watch live status (Ctrl+C exits):" not in output
        or output.rstrip().splitlines()[-1].strip() != "mirage-status"
        or "tmux" in output.lower()
    ):
        _fail("install.supervisor.operator_guidance", f"rc={result.returncode} output={output!r}")
        return

    # The closing summary is the only place an operator is told how to drive the
    # node, so every tool they need on day one has to appear there.
    missing = [
        command
        for command in (
            "mirage-status",
            "mirage-domain --set",
            "mirage-logs",
            "mirage-update",
            "mirage-backup",
            "mirage-restore",
        )
        if command not in output
    ]
    if "Commands:" not in output or missing:
        _fail("install.supervisor.command_summary", f"closing summary omits {missing or 'the Commands block'}")
        return

    if 'if [[ "$confirm" != "replace" ]]; then' not in installer:
        _fail("install.supervisor.replace_token", "replacement must require typing exactly replace")
        return
    _pass("install.supervisor.runtime")


def _test_public_cli_help() -> None:
    """Public host tools document -h/--help and reject unknown arguments."""
    tools = {
        "mirage-status": ["--once", "--json", "--interval"],
        "mirage-update": ["--status", "--rollback"],
        "mirage-backup": ["--output", "--stdout", "--with-media"],
        "mirage-restore": ["--check"],
        "mirage-domain": ["--set", "--status", "--remove"],
        "mirage-logs": ["--lines", "--once"],
        "mirage-restart": [],
        "mirage-unjail": [],
    }
    for name, flags in tools.items():
        path = os.path.join(REPO_ROOT, "deploy", "hosttools", name)
        body = Path(path).read_text(encoding="utf-8")
        if "-h|--help" not in body and "-h|--help)" not in body:
            _fail(f"install.cli.{name}.help", f"{name} does not handle -h/--help")
            return
        for flag in flags:
            if flag not in body:
                _fail(f"install.cli.{name}.{flag}", f"{name} missing {flag}")
                return
        if name == "mirage-update":
            if "unknown argument" not in body:
                _fail(f"install.cli.{name}.unknown", f"{name} does not reject unknown arguments")
                return
            help_r = _run(["bash", path, "--help"])
            if help_r.returncode != 0 or "Usage: mirage-update" not in (help_r.stdout or ""):
                _fail(
                    "install.cli.mirage-update.help_before_lock",
                    f"rc={help_r.returncode} out={help_r.stdout} err={help_r.stderr}",
                )
                return
            unknown_r = _run(["bash", path, "--not-a-real-flag"])
            if unknown_r.returncode != 2:
                _fail("install.cli.mirage-update.unknown_rc", f"rc={unknown_r.returncode} err={unknown_r.stderr}")
                return
            continue
        result = _run(["bash", path, "--not-a-real-flag"])
        if result.returncode == 0:
            _fail(f"install.cli.{name}.unknown", f"{name} accepted an unknown flag")
            return
    restore = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-restore")).read_text(encoding="utf-8")
    if "Type exactly 'restore'" not in restore:
        _fail("install.cli.restore.confirm", "mirage-restore must require typing restore")
        return
    domain = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-domain")).read_text(encoding="utf-8")
    if "Type exactly 'remove'" not in domain:
        _fail("install.cli.domain.remove", "mirage-domain --remove must require typing remove")
        return
    conflict = _run(
        ["bash", os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-domain"), "--set", "example.com", "--status"]
    )
    if conflict.returncode != 2 or "cannot be combined" not in (conflict.stderr or ""):
        _fail("install.cli.domain.conflict", f"rc={conflict.returncode} err={conflict.stderr}")
        return
    backup = Path(os.path.join(REPO_ROOT, "deploy", "online_backup.py")).read_text(encoding="utf-8")
    restore_py = Path(os.path.join(REPO_ROOT, "deploy", "online_restore.py")).read_text(encoding="utf-8")
    if "priv_validator_state.json" not in backup or "priv_validator_state.json" not in restore_py:
        _fail("install.cli.backup.signer", "backup/restore must name and exclude signer state")
        return
    if "FORBIDDEN_NAMES" not in restore_py:
        _fail("install.cli.restore.forbidden", "restore must refuse chain DB paths")
        return
    updater = Path(UPDATE_SH).read_text(encoding="utf-8")
    upgrader = Path(UPGRADE_SH).read_text(encoding="utf-8")
    # Arming a governed upgrade is mirage-upgrade's job, and only its job:
    # leaving the old flag in place would keep two names for one action.
    if "arm_governed_upgrade" not in upgrader:
        _fail("install.cli.upgrade.arm", "mirage-upgrade cannot arm a governed upgrade")
        return
    if "--prepare" in updater:
        _fail("install.cli.update.prepare_removed", "mirage-update still accepts --prepare; it is now mirage-upgrade")
        return
    if "activate_if_halted" not in updater:
        _fail("install.cli.update.activate", "mirage-update is missing the governed-halt activator")
        return
    if "upgrade-info.json" not in updater:
        _fail("install.cli.update.marker", "activation must require the Cosmos upgrade marker")
        return
    # An operator who reaches for the old spelling must be told the new one
    # rather than silently doing nothing.
    stale = _run(["bash", UPDATE_SH, "--prepare"])
    if stale.returncode != 2:
        _fail("install.cli.update.prepare_rc", f"rc={stale.returncode} err={stale.stderr}")
        return
    upgrade_help = _run(["bash", UPGRADE_SH, "--help"])
    if upgrade_help.returncode != 0 or "Usage: mirage-upgrade" not in (upgrade_help.stdout or ""):
        _fail("install.cli.upgrade.help", f"rc={upgrade_help.returncode} out={upgrade_help.stdout}")
        return
    upgrade_unknown = _run(["bash", UPGRADE_SH, "--not-a-real-flag"])
    if upgrade_unknown.returncode != 2:
        _fail("install.cli.upgrade.unknown_rc", f"rc={upgrade_unknown.returncode} err={upgrade_unknown.stderr}")
        return
    # Both tools must be installed, or the rename strands the governed path.
    for source, label in ((updater, "mirage-update"), (Path(INSTALL_SH).read_text(encoding="utf-8"), "install.sh")):
        if "mirage-update mirage-upgrade" not in source:
            _fail("install.cli.upgrade.installed", f"{label} does not install mirage-upgrade")
            return
    _pass("install.cli.public_contract")


def _test_completed_installer_updates() -> None:
    """Re-running the one-line installer must update without extra operator commands."""
    function = _shell_function(INSTALL_SH, "update_completed_install")
    body = Path(INSTALL_SH).read_text(encoding="utf-8")
    if "if state_at_least done; then\n    update_completed_install" not in body:
        _fail("install.completed.one_line", "completed installs still exit instead of updating")
        return

    with tempfile.TemporaryDirectory(prefix="completed-update-") as tmpdir:
        state = os.path.join(tmpdir, "state.json")
        calls = os.path.join(tmpdir, "calls")
        bindir = os.path.join(tmpdir, "bin")
        os.makedirs(bindir)
        image = "ghcr.io/miragefoundation/mirage-node@sha256:" + "a" * 64
        updater = os.path.join(bindir, "mirage-update")
        Path(updater).write_text(
            f"""#!/bin/bash
set -euo pipefail
echo "$*" >> {calls!r}
if [[ "${{1:-}}" == "--tick" ]]; then
  python3 - <<'PY'
import json
open({state!r}, "w").write(json.dumps({{"staged": {image!r}}}) + "\\n")
PY
fi
""",
            encoding="utf-8",
        )
        os.chmod(updater, 0o755)
        script = f"""
set -euo pipefail
PATH={bindir!r}:$PATH
UPDATE_STATE_FILE={state!r}
die() {{ echo "ERROR: $*" >&2; exit 1; }}
{function}
update_completed_install
"""
        result = _run(["bash", "-c", script])
        recorded = Path(calls).read_text(encoding="utf-8").splitlines()
        if result.returncode != 0:
            _fail(
                "install.completed.update_exit",
                f"rc={result.returncode} out={result.stdout} err={result.stderr}",
            )
            return
        if recorded != ["--tick", f"--refresh-hosttools --image {image}", ""]:
            _fail("install.completed.update_sequence", f"calls={recorded}")
            return
    _pass("install.completed.single_line_updates")


def _test_resume_refreshes_amended_release() -> None:
    """An incomplete install must not remain pinned to an image that failed."""
    function = _shell_function(INSTALL_SH, "refresh_manifests_for_resume")
    with tempfile.TemporaryDirectory(prefix="resume-manifest-") as tmp:
        pinned = os.path.join(tmp, "pinned")
        fetched = os.path.join(tmp, "fetched")
        os.makedirs(pinned)
        os.makedirs(fetched)

        def write_manifests(directory: str, release_id: int, image: str, generation: int = 2) -> None:
            Path(directory, "manifest.json").write_text(
                json.dumps({"release_id": release_id, "image": image}), encoding="utf-8"
            )
            Path(directory, "network.json").write_text(json.dumps({"generation": generation}), encoding="utf-8")

        old_image = "ghcr.io/miragefoundation/mirage-node@sha256:" + "a" * 64
        new_image = "ghcr.io/miragefoundation/mirage-node@sha256:" + "b" * 64
        write_manifests(pinned, 1037000, old_image)
        write_manifests(fetched, 1037000, new_image)
        script = (
            "set -euo pipefail\n"
            "PREVIOUS_IMAGE=''\nRESUME_IMAGE_CHANGED=0\nMANIFEST_DIR=''\n"
            f"use_pinned_manifests() {{ MANIFEST_DIR={pinned!r}; }}\n"
            f"fetch_manifests() {{ MANIFEST_DIR={fetched!r}; }}\n"
            "verify_manifests() { :; }\npin_manifests() { echo pinned; }\n"
            'die() { echo "ERROR: $*" >&2; exit 1; }\n'
            + function
            + '\nrefresh_manifests_for_resume\nprintf "%s|%s" "$RESUME_IMAGE_CHANGED" "$PREVIOUS_IMAGE"\n'
        )
        r = _run(["bash", "-c", script])
        if r.returncode != 0 or not r.stdout.endswith(f"1|{old_image}"):
            _fail("install.resume.amended_release", f"rc={r.returncode} out={r.stdout!r} err={r.stderr!r}")
            return

        write_manifests(fetched, 1036999, new_image)
        r = _run(["bash", "-c", script])
        if r.returncode == 0 or "older than pinned release" not in r.stderr:
            _fail("install.resume.rejects_downgrade", f"rc={r.returncode} err={r.stderr!r}")
            return
    _pass("install.resume.refreshes_amended_release")


def _test_partial_chain_reset_preserves_state() -> None:
    """A failed height-zero InitGenesis is moved aside before a clean retry."""
    function = _shell_function(INSTALL_SH, "reset_partial_chain_init")
    with tempfile.TemporaryDirectory(prefix="partial-chain-") as tmp:
        root = os.path.join(tmp, ".mirage")
        data = os.path.join(root, "node", "data")
        config = os.path.join(root, "node", "config")
        os.makedirs(data)
        os.makedirs(config)
        state = '{"height":"0","round":0,"step":0}\n'
        Path(data, "priv_validator_state.json").write_text(state, encoding="utf-8")
        Path(data, "application.db").mkdir()
        Path(data, "application.db", "CURRENT").write_text("partial", encoding="utf-8")
        Path(config, "genesis.json").write_text("verified source genesis", encoding="utf-8")
        Path(root, ".initialized").write_text("", encoding="utf-8")

        function = function.replace("/root/.mirage", root)
        script = (
            "set -euo pipefail\n"
            "PREVIOUS_IMAGE=old-image\nIMAGE=new-image\n"
            'die() { echo "ERROR: $*" >&2; exit 1; }\n'
            "docker() { :; }\n" + function + "\nreset_partial_chain_init\n"
        )
        r = _run(["bash", "-c", script])
        captures = list(Path(root, ".failed_install_forensics").glob("*"))
        if r.returncode != 0 or len(captures) != 1:
            _fail("install.resume.partial_snapshot", f"rc={r.returncode} captures={captures} err={r.stderr!r}")
            return
        capture = captures[0]
        if not Path(capture, "data", "application.db", "CURRENT").is_file():
            _fail("install.resume.partial_data", "partial chain database was not preserved")
            return
        if Path(data, "priv_validator_state.json").read_text(encoding="utf-8") != state:
            _fail("install.resume.validator_state", "validator state was not restored byte-for-byte")
            return
        if Path(config, "genesis.json").exists() or Path(root, ".initialized").exists():
            _fail("install.resume.bootstrap_reset", "old genesis or initialization marker survived")
            return
        manifest = Path(capture, "MANIFEST.txt").read_text(encoding="utf-8")
        if "previous_image=old-image" not in manifest or "new_image=new-image" not in manifest:
            _fail("install.resume.snapshot_manifest", manifest)
            return
    _pass("install.resume.partial_chain_preserved")


def _test_activation_and_registration_waits() -> None:
    """Slow must not be mistaken for broken on the updater and enrollment paths.

    The updater rolls a release back when this wait expires, so a migration that
    outlasts it would revert a healthy release; create_validator declared
    failure before the 2m validity window of its own unordered transaction.
    """
    wait = _shell_function(UPDATE_SH, "wait_for_rpc")
    if "budget=900" not in wait or "RestartCount" not in wait:
        _fail("install.activation.budget", "updater wait is not the padded, crash-aware one")
        return
    if ">/dev/null 2>&1" not in wait:
        _fail("install.activation.probe_noise", "expected RPC startup misses still print curl errors")
        return

    def run_wait(running: str, restarts: str, rpc_after: int) -> subprocess.CompletedProcess:
        return _run(
            [
                "bash",
                "-c",
                f"""set -uo pipefail
sleep() {{ :; }}
n=0
curl() {{ n=$((n + 1)); (( n > {rpc_after} )); }}
docker() {{
  case "$*" in
    *"{{{{.State.Running}}}}"*) echo {running} ;;
    *"{{{{.State.Restarting}}}}"*) echo false ;;
    *"{{{{.RestartCount}}}}"*) {restarts} ;;
    *) return 1 ;;
  esac
}}
{wait}
wait_for_rpc
""",
            ]
        )

    r = run_wait("true", "echo 0", 3)
    if r.returncode != 0 or "RPC ready" not in (r.stdout or ""):
        _fail("install.activation.slow_start", f"a slow but healthy start was failed: {r.stdout} {r.stderr}")
        return
    r = run_wait("false", "echo 0", 10**9)
    if r.returncode == 0 or "no longer running" not in (r.stderr or ""):
        _fail("install.activation.dead", f"a dead container was not detected: rc={r.returncode} {r.stderr}")
        return

    validator = Path(REPO_ROOT, "deploy", "create_validator.sh").read_text(encoding="utf-8")
    window = re.search(r"--timeout-duration (\d+)m", validator)
    timeout = re.search(r"^REGISTRATION_TIMEOUT=(\d+)$", validator, re.MULTILINE)
    if not window or not timeout:
        _fail("install.registration.literals", "cannot read the tx validity window or the registration wait")
        return
    if int(timeout.group(1)) <= int(window.group(1)) * 60:
        _fail(
            "install.registration.window",
            f"registration wait {timeout.group(1)}s does not outlast the {window.group(1)}m tx window",
        )
        return
    _pass("install.waits.outlast_migrations_and_tx_window")


def _test_release_workflow_files_tracked() -> None:
    """Release CI runs from a fresh checkout, so it cannot rely on ignored files.

    Every release tag from v1.36.4 to v1.36.7 failed the published-manifest job
    because it imports scripts.finalize_release_manifest, which the scripts/*
    ignore rule kept out of every clone while it sat in the working tree.

    The runtime image ships neither the workflow nor git metadata, so the list of
    files is named here. In the image their presence is the evidence, since a
    CI-built image is built from a checkout. On a checkout the workflow is re-read
    to prove the list has not drifted and that git tracks every entry.
    """
    missing = [path for path in RELEASE_CI_FILES if not Path(REPO_ROOT, path).is_file()]
    if missing:
        _fail("install.release_ci.missing", f"release CI needs files this build does not carry: {missing}")
        return
    workflow_path = Path(REPO_ROOT, ".github", "workflows", "release.yml")
    if workflow_path.is_file() and Path(REPO_ROOT, ".git").exists():
        workflow = workflow_path.read_text(encoding="utf-8")
        referenced = {
            f"{package}/{module}.py" for package, module in re.findall(r"from (scripts|deploy)\.(\w+) import", workflow)
        }
        referenced.update(re.findall(r"(?:python3|bash|sh) ((?:scripts|deploy)/[\w./-]+)", workflow))
        if referenced != set(RELEASE_CI_FILES):
            _fail(
                "install.release_ci.drift",
                f"workflow references {sorted(referenced)}, this test checks {sorted(RELEASE_CI_FILES)}",
            )
            return
        untracked = [
            path
            for path in RELEASE_CI_FILES
            if _run(["git", "-C", REPO_ROOT, "ls-files", "--error-unmatch", path]).returncode != 0
        ]
        if untracked:
            _fail("install.release_ci.untracked", f"release CI needs files git does not track: {untracked}")
            return
    _pass(f"install.release_ci.carries_all_{len(RELEASE_CI_FILES)}_referenced_files")


def _test_docker_context_excludes_private_key() -> None:
    forbidden = (".release_signing.pem", ".env", ".envrc", "release-manifest.candidate.json")
    if _INSIDE_CONTAINER:
        # .dockerignore is itself not shipped, and inside the image the artifact
        # can be checked directly, which is the stronger statement: the release is
        # built on the operator's host where the signing key does exist, so a
        # context leak would put the real key here.
        present = [name for name in forbidden if Path(REPO_ROOT, name).exists()]
        if present:
            _fail("install.image.secrets", f"sensitive build-context files present in runtime image: {present}")
            return
    else:
        dockerignore = Path(REPO_ROOT, ".dockerignore").read_text(encoding="utf-8")
        missing = [name for name in forbidden if name not in dockerignore]
        if missing:
            _fail("install.image.secrets", f"sensitive files are not excluded from the image build context: {missing}")
            return
    if not Path(PUBKEY).is_file():
        _fail("install.image.pubkey", "runtime image is missing the public trust anchor")
        return
    _pass("install.image.secrets_excluded")


def _test_pubkey_fingerprint() -> None:
    r = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", PUBKEY, "-outform", "DER"],
        capture_output=True,
    )
    if r.returncode != 0:
        _fail("install.pubkey.openssl", r.stderr.decode("utf-8", "replace"))
        return
    raw = r.stdout[-32:]
    fp = raw.hex()
    if fp != EXPECTED_FP:
        _fail("install.pubkey.fingerprint", f"got {fp} want {EXPECTED_FP}")
        return
    install_body = Path(INSTALL_SH).read_text(encoding="utf-8")
    if EXPECTED_FP not in install_body:
        _fail("install.pubkey.inlined", "install.sh missing EXPECTED_PUBKEY_FINGERPRINT")
        return
    # The installer must be able to check the anchor before it installs anything,
    # so the fingerprint has to come out of base-image tools alone.
    script = _install_functions_only() + f'\npubkey_fingerprint "{PUBKEY}"\n'
    r2 = _run(["bash", "-c", script])
    if r2.returncode != 0 or r2.stdout.strip() != EXPECTED_FP:
        _fail(
            "install.pubkey.openssl_only",
            f"pubkey_fingerprint gave {r2.stdout.strip()!r} rc={r2.returncode} err={r2.stderr[-200:]}",
        )
        return
    _pass("install.pubkey_fingerprint", fingerprint=fp)


def _test_manifest_signatures() -> None:
    checked_in = _run(
        [
            "python3",
            RELEASE_VERIFY,
            "verify",
            "--manifest",
            NETWORK_JSON,
            "--pubkey",
            PUBKEY,
        ]
    )
    if checked_in.returncode != 0:
        _fail("install.manifest.checked_in_signature", checked_in.stderr[-400:])
        return
    _pass("install.manifest.checked_in_signature")

    sample = json.loads(Path(NETWORK_JSON).read_text(encoding="utf-8"))
    # Pin the validity window so this case does not start failing on the day the
    # checked-in manifest expires. Expiry itself is covered below.
    sample["issued_at"] = "2026-01-01T00:00:00Z"
    sample["expires_at"] = "2099-01-01T00:00:00Z"
    with tempfile.TemporaryDirectory(prefix="manifest-sig-") as tmp:
        priv, pub = _ed25519_keypair(tmp)
        path = os.path.join(tmp, "network.json")
        Path(path).write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")
        r = _run(
            [
                "python3",
                RELEASE_VERIFY,
                "sign",
                "--manifest",
                path,
                "--privkey",
                priv,
            ]
        )
        if r.returncode != 0:
            _fail("install.manifest.sign", r.stderr)
            return
        r = _run(
            [
                "python3",
                RELEASE_VERIFY,
                "verify",
                "--manifest",
                path,
                "--pubkey",
                pub,
            ]
        )
        if r.returncode != 0:
            _fail("install.manifest.verify_ok", r.stderr)
            return
        _pass("install.manifest.verify_matching_key")

        tampered = json.loads(Path(path).read_text(encoding="utf-8"))
        tampered["generation"] = int(tampered["generation"]) + 1
        Path(path).write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
        r = _run(
            [
                "python3",
                RELEASE_VERIFY,
                "verify",
                "--manifest",
                path,
                "--pubkey",
                pub,
            ]
        )
        if r.returncode == 0:
            _fail("install.manifest.tampered", "accepted a tampered body")
            return
        _pass("install.manifest.rejects_tampered_body")

        Path(path).write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")
        _run(["python3", RELEASE_VERIFY, "sign", "--manifest", path, "--privkey", priv])
        other_priv, other_pub = _ed25519_keypair(tmp)
        r = _run(
            [
                "python3",
                RELEASE_VERIFY,
                "verify",
                "--manifest",
                path,
                "--pubkey",
                other_pub,
            ]
        )
        if r.returncode == 0:
            _fail("install.manifest.wrong_key", "accepted a signature from another key")
            return
        _pass("install.manifest.rejects_wrong_key")

        expired = {**sample, "issued_at": "2020-01-01T00:00:00Z", "expires_at": "2020-04-01T00:00:00Z"}
        Path(path).write_text(json.dumps(expired, indent=2) + "\n", encoding="utf-8")
        payload_path = os.path.join(tmp, "expired.canonical")
        Path(payload_path).write_bytes(
            json.dumps(expired, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        sign_result = _run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                priv,
                "-rawin",
                "-in",
                payload_path,
                "-out",
                path + ".sig",
            ]
        )
        if sign_result.returncode != 0:
            _fail("install.manifest.expired_fixture", sign_result.stderr)
            return
        r = _run(["python3", RELEASE_VERIFY, "verify", "--manifest", path, "--pubkey", pub])
        if r.returncode == 0:
            _fail("install.manifest.expired", "accepted a correctly signed but expired manifest")
            return
        if "expired" not in ((r.stderr or "") + (r.stdout or "")):
            _fail("install.manifest.expired_message", f"unexpected: {r.stderr[-200:]}")
            return
        _pass("install.manifest.rejects_expired")


def _test_collision_guard_paginates() -> None:
    with tempfile.TemporaryDirectory(prefix="collision-pages-") as tmp:
        manifest_dir = os.path.join(tmp, "manifests")
        os.makedirs(manifest_dir)
        Path(manifest_dir, "network.json").write_text(
            json.dumps({"rest": ["https://one.invalid", "https://two.invalid"]}),
            encoding="utf-8",
        )
        calls = os.path.join(tmp, "calls")
        function = _shell_function(INSTALL_SH, "collision_guard").replace(
            "/root/.mirage",
            os.path.join(tmp, "host-mirage"),
        )
        script = f"""set -euo pipefail
MANIFEST_DIR={manifest_dir!r}
MNEMONIC="abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
IMAGE=test
ADDRESS=mirage1test
CALLS={calls!r}
die() {{ echo "ERROR: $*" >&2; exit 1; }}
docker() {{
  local mount="" arg
  [[ "$*" == *"derive_consensus_key.py"* ]] || return 1
  for arg in "$@"; do
    if [[ -n "$mount" ]]; then
      host="${{arg%%:*}}"
      mkdir -p "$host/node/config"
      printf '%s\\n' '{{"pub_key":{{"value":"TARGETPUB"}}}}' > "$host/node/config/priv_validator_key.json"
      return 0
    fi
    [[ "$arg" == -v ]] && mount=next
  done
  return 1
}}
agree_json() {{
  echo "$2" >> "$CALLS"
  if [[ "$2" == *"pagination.key=NEXT%2B%2F%3D"* ]]; then
    printf '%s\\n' '{{"validators":[{{"consensus_pubkey":{{"key":"TARGETPUB"}},"operator_address":"miragevaloper1existing"}}],"pagination":{{"next_key":null}}}}'
  else
    printf '%s\\n' '{{"validators":[],"pagination":{{"next_key":"NEXT+/="}}}}'
  fi
}}
confirm_validator_replacement() {{
  die "this seed's consensus key is already a validator ($2) on another host"
}}
{function}
collision_guard
"""
        r = _run(["bash", "-c", script])
        paths = Path(calls).read_text(encoding="utf-8").splitlines() if os.path.isfile(calls) else []
        if r.returncode == 0 or "already a validator" not in r.stderr or len(paths) != 2:
            _fail(
                "install.collision.pagination",
                f"rc={r.returncode} calls={paths} out={r.stdout} err={r.stderr}",
            )
            return
    _pass("install.collision.paginates")


def _test_create_validator_syncing() -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"result": {"sync_info": {"catching_up": True, "latest_block_height": "12"}}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="create-val-") as tmp:
            manifest = {
                "self_delegation_umirage": "5000000000000",
                "min_liquid_umirage": "1000000000000",
                "activation_balance_umirage": "10000000000000",
            }
            man_path = os.path.join(tmp, "network.json")
            Path(man_path).write_text(json.dumps(manifest), encoding="utf-8")
            env = {
                **os.environ,
                "NETWORK_MANIFEST": man_path,
                "RPC_URL": f"http://127.0.0.1:{port}",
                "NODE_HOME": os.path.join(tmp, "node"),
                "ROOT_DIR": REPO_ROOT,
            }
            r = _run(["bash", CREATE_VALIDATOR], env=env, timeout=20)
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                _fail("install.create_validator.syncing_exit", f"exit {r.returncode}: {out[-400:]}")
                return
            if "STATE=syncing" not in out:
                _fail("install.create_validator.syncing_state", f"output: {out[-400:]}")
                return
            _pass("install.create_validator.catching_up_syncing")
    finally:
        httpd.shutdown()


def _test_create_validator_gas_price() -> None:
    body = Path(CREATE_VALIDATOR).read_text(encoding="utf-8")
    if "--gas-prices 0.025" in body or "--gas-prices 0.025umirage" in body:
        _fail("install.create_validator.no_0025", "create_validator.sh still hardcodes 0.025umirage")
        return
    if "load_min_gas_price" not in body:
        _fail("install.create_validator.app_toml_gas", "does not read minimum-gas-prices from app.toml")
        return
    if "--broadcast-mode sync" not in body:
        _fail("install.create_validator.broadcast_sync", "missing --broadcast-mode sync")
        return
    if "--unordered --timeout-duration 2m" not in body:
        _fail("install.create_validator.unordered", "create-validator transaction is not unordered")
        return
    _pass("install.create_validator.gas_from_app_toml")


def _test_create_validator_min_self_delegation() -> None:
    """min-self-delegation must stay well below the stake, or one slash unbonds forever."""
    body = Path(CREATE_VALIDATOR).read_text(encoding="utf-8")
    net = json.loads(Path(NETWORK_JSON).read_text(encoding="utf-8"))
    match = __import__("re").search(r'^MIN_SELF="(\d+)"', body, __import__("re").MULTILINE)
    if not match:
        _fail("install.create_validator.min_self_literal", "MIN_SELF is not a fixed umirage amount")
        return
    min_self = int(match.group(1))
    if min_self >= int(net["self_delegation_umirage"]):
        _fail(
            "install.create_validator.min_self_too_high",
            f"min-self-delegation {min_self} is not below the {net['self_delegation_umirage']} stake",
        )
        return
    if "$BIN q staking validators" in body:
        _fail(
            "install.create_validator.paginated_scan",
            "scans the paginated validator list instead of querying its own operator address",
        )
        return
    _pass("install.create_validator.min_self_delegation", min_self=min_self)


def _test_releases_are_reachable_from_any_version() -> None:
    """A node must be able to reach the current release from any older one.

    min_prior_version made the updater refuse a release unless the node was on
    the immediately preceding one, which CI filled in from tag history rather
    than from any real requirement. A node two releases behind could never
    comply: only the newest manifest is ever published, so the intermediate
    release it was told to install first was not fetchable. Migrations do not
    need the stepping stone either — the runner applies every migration the node
    has not run yet.
    """
    # A published manifest that still carried the field would be rejected outright
    # by the verifier below, which accepts no unknown fields, so what has to be
    # checked here is the code that could reintroduce the requirement. The image
    # ships whichever manifest existed when it was built, which for a published
    # release is the previous one, so it is not the artifact to assert on.
    watched = {
        "deploy/hosttools/mirage-update": "the updater",
        "deploy/release_verify.py": "the manifest verifier",
        "release/manifest.schema.json": "the manifest schema",
        ".github/workflows/release.yml": "release CI",
    }
    present = [
        label
        for path, label in watched.items()
        if Path(REPO_ROOT, path).is_file() and "min_prior" in Path(REPO_ROOT, path).read_text(encoding="utf-8")
    ]
    if present:
        _fail("install.updater.no_stepping_stone", f"a per-step version requirement is back in: {present}")
        return

    # Migrations are what a skipped release would actually have carried, and the
    # runner selects them by what this node has not applied, not by version.
    runner = Path(REPO_ROOT, "deploy", "migrations", "__init__.py").read_text(encoding="utf-8")
    if "key not in completed" not in runner:
        _fail("install.updater.migrations_pending", "migrations are no longer selected by what the node has not run")
        return
    _pass("install.updater.any_older_version_can_reach_the_current_release")


def _test_updater_gates() -> None:
    """The updater must not re-stage what is running or replay an old manifest."""
    update = Path(REPO_ROOT, "deploy", "hosttools", "mirage-update").read_text(encoding="utf-8")
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    if "last_release_id" not in install or "/var/lib/mirage/update" not in install:
        _fail("install.updater.seed_state", "install.sh does not seed the updater state")
        return
    for needle, name in (
        ("generation < last_gen", "generation_rollback"),
        ("min_release", "min_release"),
    ):
        if needle not in update:
            _fail(f"install.updater.{name}", f"mirage-update has no {needle} gate")
            return
    if "|| true" in update.split("fetch_verify()")[1].split("}")[0]:
        _fail("install.updater.sig_required", "fetch_verify tolerates a missing signature")
        return
    lines = update.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("version_at_least()"))
    end = next(i for i, line in enumerate(lines[start:], start) if line == "}")
    script = (
        "\n".join(lines[start : end + 1])
        + "\n"
        + (
            'for c in "v1.36.2 v1.36.0 0" "v1.35.0 v1.36.0 1" "v1.36.0 v1.36.0 0" "v1.9.0 v1.10.0 1"; do\n'
            "  set -- $c\n"
            '  if version_at_least "$1" "$2"; then got=0; else got=1; fi\n'
            '  [ "$got" = "$3" ] || { echo "WRONG $1 $2 got=$got"; exit 1; }\n'
            "done\n"
            "echo COMPARE_OK\n"
        )
    )
    r = _run(["bash", "-c", script])
    if r.returncode != 0 or "COMPARE_OK" not in r.stdout:
        _fail("install.updater.version_compare", f"{r.stdout.strip()} {r.stderr[-200:]}")
        return
    if not _test_updater_halt_and_rollback():
        return
    if not _test_updater_network_only_refresh():
        return
    _pass("install.updater.gates")


def _test_updater_halt_and_rollback() -> bool:
    with tempfile.TemporaryDirectory(prefix="updater-policy-") as tmp:
        state = os.path.join(tmp, "state.json")
        launch_log = os.path.join(tmp, "launch.log")
        launcher = os.path.join(tmp, "launch")
        Path(launcher).write_text(f'#!/bin/sh\necho "$*" >> {launch_log}\n', encoding="utf-8")
        os.chmod(launcher, 0o755)
        base = {
            "active": "current",
            "previous": "previous",
            "staged": "next",
            "staged_activation": "upgrade-halt",
            "active_rollback_safe": False,
            "active_consensus_breaking": True,
        }
        Path(state).write_text(json.dumps(base), encoding="utf-8")
        halt_script = (
            "set -euo pipefail\n"
            f'STATE_FILE="{state}"\nLAUNCH="{launcher}"\n'
            + _shell_function(UPDATE_SH, "activate_staged")
            + "activate_staged\n"
        )
        r = _run(["bash", "-c", halt_script])
        if r.returncode == 0 or "cannot be activated manually" not in r.stderr or os.path.exists(launch_log):
            _fail("install.updater.halt_policy", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return False

        rollback_script = (
            "set -euo pipefail\n"
            f'STATE_FILE="{state}"\nLAUNCH="{launcher}"\n' + _shell_function(UPDATE_SH, "rollback") + "rollback\n"
        )
        r = _run(["bash", "-c", rollback_script])
        if r.returncode == 0 or "does not permit rollback" not in r.stderr or os.path.exists(launch_log):
            _fail("install.updater.rollback_policy", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return False
    return True


def _test_updater_network_only_refresh() -> bool:
    with tempfile.TemporaryDirectory(prefix="updater-network-") as tmp:
        current_version = Path(VERSION_FILE).read_text(encoding="utf-8").strip()
        home = os.path.join(tmp, "home")
        work = os.path.join(tmp, "work")
        os.makedirs(os.path.join(home, ".mirage", "env"), exist_ok=True)
        os.makedirs(work, exist_ok=True)
        release = {
            "version": current_version,
            "release_id": 7,
            "commit": "0" * 40,
            "image": "ghcr.io/miragefoundation/mirage-node@sha256:" + ("1" * 64),
            "activation": "ordinary",
            "upgrade_name": "",
            "rollback_safe": True,
            "consensus_breaking": False,
        }
        network = json.loads(Path(NETWORK_JSON).read_text(encoding="utf-8"))
        network["generation"] = 2
        release_path = os.path.join(tmp, "release.json")
        network_path = os.path.join(tmp, "network.json")
        Path(release_path).write_text(json.dumps(release), encoding="utf-8")
        Path(network_path).write_text(json.dumps(network), encoding="utf-8")
        Path(os.path.join(home, ".mirage", "env", "release-manifest.json")).write_text(
            json.dumps(release), encoding="utf-8"
        )
        old_network = {**network, "generation": 1}
        Path(os.path.join(home, ".mirage", "env", "network-manifest.json")).write_text(
            json.dumps(old_network), encoding="utf-8"
        )
        state_path = os.path.join(tmp, "state.json")
        Path(state_path).write_text(
            json.dumps({"last_release_id": 7, "last_network_generation": 1}),
            encoding="utf-8",
        )
        functions = "".join(_shell_function(UPDATE_SH, name) for name in ("version_at_least", "canonical_hash", "tick"))
        script = f"""set -euo pipefail
HOME={home!r}
tmp={work!r}
STATE_FILE={state_path!r}
MANIFEST_URL=release
NETWORK_URL=network
fetch_verify() {{
  if [[ "$1" == release ]]; then cp {release_path!r} "$2"; else cp {network_path!r} "$2"; fi
  printf sig > "$2.sig"
}}
json_field() {{ python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }}
install_network_manifest() {{ cp "$1" "$HOME/.mirage/env/network-manifest.json"; }}
docker() {{ echo "docker should not run for network-only refresh" >&2; return 99; }}
install_hosttools_from_image() {{ echo "hosttools should not install" >&2; return 99; }}
{functions}
tick
"""
        r = _run(["bash", "-c", script])
        if r.returncode != 0:
            _fail("install.updater.network_only", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return False
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        installed = json.loads(Path(home, ".mirage", "env", "network-manifest.json").read_text(encoding="utf-8"))
        if state.get("last_network_generation") != 2 or installed.get("generation") != 2:
            _fail("install.updater.network_only_state", f"state={state} network={installed.get('generation')}")
            return False
    return True


def _test_hosttool_paths() -> None:
    """mirage-verify has to find the verifier where install.sh puts it, or the updater is dead."""
    verify = Path(REPO_ROOT, "deploy", "hosttools", "mirage-verify").read_text(encoding="utf-8")
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    for path in ("/usr/local/share/mirage/release_verify.py", "/usr/local/share/mirage/pubkey.pem"):
        if path not in verify:
            _fail("install.hosttools.verify_paths", f"mirage-verify never looks at {path}")
            return
        if path not in install:
            _fail("install.hosttools.install_paths", f"install.sh never writes {path}")
            return
    if "image pubkey" not in install:
        _fail("install.hosttools.pubkey_anchor", "install.sh does not compare the image's pubkey to its own")
        return
    _pass("install.hosttools.paths")


def _test_updater_hosttools_on_activate_only() -> None:
    """Staging must not replace host tools; activation installs them after a healthy launch."""
    tick = _shell_function(UPDATE_SH, "tick")
    activate = _shell_function(UPDATE_SH, "activate_staged")
    if "install_hosttools_from_image" in tick:
        _fail("install.updater.tick_installs_hosttools", "tick() still installs host tools from a staged image")
        return
    idx_launch = activate.find('"$LAUNCH"')
    idx_tools = activate.find("install_hosttools_from_image")
    if idx_tools < 0:
        _fail("install.updater.activate_installs_hosttools", "activate_staged() never installs host tools")
        return
    if idx_launch < 0 or idx_tools < idx_launch:
        _fail(
            "install.updater.hosttools_before_launch",
            "host tools would install before the staged container is healthy",
        )
        return
    _pass("install.updater.hosttools_on_activate_only")


def _test_updater_refreshes_before_activation() -> None:
    """A manual update must supersede an older image staged by the hourly tick."""
    fetch = _shell_function(UPDATE_SH, "fetch_verify")
    if "mirage_cache=" not in fetch:
        _fail("install.updater.cache_bust", "signed manifests can remain stale in the GitHub edge cache")
        return

    with tempfile.TemporaryDirectory(prefix="updater-refresh-") as tmpdir:
        calls = os.path.join(tmpdir, "curl-calls")
        fetch_script = f"""set -euo pipefail
VERIFY=true
PUBKEY=unused
curl() {{ printf '%s\\n' "$*" >> {calls!r}; }}
{fetch}
fetch_verify 'https://updates.example/manifest.json?token=abc' {os.path.join(tmpdir, "manifest.json")!r}
"""
        fetch_result = _run(["bash", "-c", fetch_script])
        recorded = Path(calls).read_text(encoding="utf-8").splitlines()
        if (
            fetch_result.returncode != 0
            or len(recorded) != 2
            or "manifest.json?token=abc&mirage_cache=" not in recorded[0]
            or "manifest.json.sig?token=abc&mirage_cache=" not in recorded[1]
        ):
            _fail(
                "install.updater.cache_bust_urls",
                f"rc={fetch_result.returncode} calls={recorded} err={fetch_result.stderr!r}",
            )
            return

        update_now = _shell_function(UPDATE_SH, "update_now")
        state = os.path.join(tmpdir, "state.json")
        Path(state).write_text(json.dumps({"staged": "old-image"}) + "\n", encoding="utf-8")
        script = f"""set -euo pipefail
STATE_FILE={state!r}
tick() {{
  python3 -c 'import json,sys; open(sys.argv[1], "w").write(json.dumps({{"staged": "new-image"}}) + "\\n")' "$STATE_FILE"
  echo tick
}}
activate_staged() {{
  python3 -c 'import json,sys; print("activate " + json.load(open(sys.argv[1]))["staged"])' "$STATE_FILE"
}}
{update_now}
update_now
"""
        result = _run(["bash", "-c", script])
        if result.returncode != 0 or result.stdout.splitlines() != ["tick", "activate new-image"]:
            _fail(
                "install.updater.refreshes_staged",
                f"rc={result.returncode} out={result.stdout!r} err={result.stderr!r}",
            )
            return
    _pass("install.updater.refreshes_before_activation")


def _test_updater_repairs_uninitialized_node() -> None:
    """A signed staged release must repair a node that is down, whatever height it signed to."""
    activate = _shell_function(UPDATE_SH, "activate_staged")
    json_field = _shell_function(UPDATE_SH, "json_field")

    with tempfile.TemporaryDirectory(prefix="updater-uninitialized-") as tmpdir:
        home = os.path.join(tmpdir, "home")
        state_dir = os.path.join(tmpdir, "state")
        data_dir = os.path.join(home, ".mirage", "node", "data")
        env_dir = os.path.join(home, ".mirage", "env")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(env_dir, exist_ok=True)
        os.makedirs(state_dir, exist_ok=True)
        state_path = os.path.join(state_dir, "state.json")
        image = "ghcr.io/miragefoundation/mirage-node@sha256:" + "a" * 64
        Path(os.path.join(env_dir, "release-manifest.json")).write_text(
            json.dumps({"image": image}) + "\n",
            encoding="utf-8",
        )
        launch = os.path.join(tmpdir, "launch")
        launched = os.path.join(tmpdir, "launched")
        Path(launch).write_text(f'#!/bin/bash\necho "$*" > {launched!r}\n', encoding="utf-8")
        os.chmod(launch, 0o755)

        def run(height: int) -> subprocess.CompletedProcess:
            Path(state_path).write_text(
                json.dumps(
                    {
                        "staged": image,
                        "staged_activation": "ordinary",
                        "staged_rollback_safe": False,
                        "staged_consensus_breaking": False,
                        "active": "old",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            Path(os.path.join(data_dir, "priv_validator_state.json")).write_text(
                json.dumps({"height": str(height), "round": 0, "step": 0}) + "\n",
                encoding="utf-8",
            )
            Path(launched).unlink(missing_ok=True)
            script = f"""
set -euo pipefail
HOME={home!r}
STATE_FILE={state_path!r}
LAUNCH={launch!r}
SAFETY_BLOCKS=500
tmp={tmpdir!r}
curl() {{ return 7; }}
query_local_rest() {{ return 7; }}
wait_for_rpc() {{ return 0; }}
install_hosttools_from_image() {{ :; }}
{json_field}
{activate}
activate_staged
"""
            return _run(["bash", "-c", script])

        result = run(0)
        if result.returncode != 0 or not os.path.isfile(launched):
            _fail(
                "install.updater.uninitialized_repair",
                f"height-zero repair failed rc={result.returncode} out={result.stdout} err={result.stderr}",
            )
            return

        # A validator halted by a consensus fault looks exactly like this: no RPC,
        # no REST, and a signed height from the blocks it managed before stopping.
        # It is the case the updater exists for, so it must not be refused.
        result = run(10)
        if result.returncode != 0 or not os.path.isfile(launched):
            _fail(
                "install.updater.halted_validator_repair",
                f"refused to update a down validator rc={result.returncode} out={result.stdout} err={result.stderr}",
            )
            return
    _pass("install.updater.repairs_uninitialized_node")


def _test_updater_refuses_catching_up() -> None:
    """A validator that has signed must not be swapped mid-sync; a height-zero node must not be stranded."""
    activate = _shell_function(UPDATE_SH, "activate_staged")
    json_field = _shell_function(UPDATE_SH, "json_field")
    with tempfile.TemporaryDirectory(prefix="updater-catchup-") as tmpdir:
        home = os.path.join(tmpdir, "home")
        state_dir = os.path.join(tmpdir, "state")
        data_dir = os.path.join(home, ".mirage", "node", "data")
        env_dir = os.path.join(home, ".mirage", "env")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(env_dir, exist_ok=True)
        os.makedirs(state_dir, exist_ok=True)
        state_path = os.path.join(state_dir, "state.json")
        image = "ghcr.io/miragefoundation/mirage-node@sha256:" + "a" * 64
        Path(os.path.join(env_dir, "release-manifest.json")).write_text(
            json.dumps({"image": image}) + "\n",
            encoding="utf-8",
        )
        launch = os.path.join(tmpdir, "launch")
        launched = os.path.join(tmpdir, "launched")
        Path(launch).write_text(f'#!/bin/bash\necho "$*" > {launched!r}\n', encoding="utf-8")
        os.chmod(launch, 0o755)

        def run(signed_height: int) -> subprocess.CompletedProcess:
            Path(state_path).write_text(
                json.dumps(
                    {
                        "staged": image,
                        "staged_activation": "ordinary",
                        "staged_rollback_safe": False,
                        "staged_consensus_breaking": False,
                        "active": "old",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            Path(os.path.join(data_dir, "priv_validator_state.json")).write_text(
                json.dumps({"height": str(signed_height), "round": 0, "step": 0}) + "\n",
                encoding="utf-8",
            )
            Path(launched).unlink(missing_ok=True)
            script = f"""
set -euo pipefail
HOME={home!r}
STATE_FILE={state_path!r}
LAUNCH={launch!r}
SAFETY_BLOCKS=500
curl() {{
  echo '{{"result":{{"sync_info":{{"catching_up":true,"latest_block_height":"12"}}}}}}'
}}
query_local_rest() {{ echo "host LCD must not be queried" >&2; return 7; }}
wait_for_rpc() {{ return 0; }}
install_hosttools_from_image() {{ :; }}
{json_field}
{activate}
activate_staged
"""
            return _run(["bash", "-c", script])

        signed = run(12)
        if signed.returncode == 0 or os.path.exists(launched):
            _fail(
                "install.updater.catching_up_refuse",
                f"activated a signing validator mid-sync: rc={signed.returncode} out={signed.stdout} err={signed.stderr}",
            )
            return
        if "catching up" not in signed.stderr and "catching up" not in signed.stdout:
            _fail(
                "install.updater.catching_up_message",
                f"missing catching-up refuse: out={signed.stdout} err={signed.stderr}",
            )
            return

        # Height zero never signed anything, so there is no partial sync to
        # protect and refusing would strand it on the broken release.
        fresh = run(0)
        if fresh.returncode != 0 or not os.path.isfile(launched):
            _fail(
                "install.updater.catching_up_height_zero",
                f"stranded a height-zero node: rc={fresh.returncode} out={fresh.stdout} err={fresh.stderr}",
            )
            return
    _pass("install.updater.refuses_catching_up")


def _test_host_tools_query_lcd_in_container() -> None:
    """LCD is not published on the host; host tools must reach it via docker exec."""
    files = (
        Path(REPO_ROOT, "deploy", "hosttools", "mirage-update"),
        Path(REPO_ROOT, "deploy", "hosttools", "mirage-restart"),
        Path(REPO_ROOT, "deploy", "hosttools", "mirage-weekly-restart.sh"),
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "1317" not in line or "curl" not in line:
                continue
            if "docker exec" in line:
                continue
            _fail(
                "install.hosttools.lcd_on_host",
                f"{path.name} curls LCD on the host: {line}",
            )
            return
        if "query_local_rest" in text and "docker exec mirage curl" not in text:
            _fail(
                "install.hosttools.lcd_helper",
                f"{path.name} defines query_local_rest without docker exec",
            )
            return
    _pass("install.hosttools.lcd_in_container")


def _test_peer_pull_requires_peer_ahead() -> None:
    """Peer-pull must refuse when local height is unknown or no peer is strictly ahead."""
    recover = os.path.join(REPO_ROOT, "scripts", "recover.sh")
    script = "set -euo pipefail\n" "LOG_FILE=\n" + _shell_function(recover, "log") + _shell_function(
        recover, "die"
    ) + _shell_function(recover, "peer_require_source_ahead")
    same = _run(["bash", "-c", script + "LOCAL_DIVERGED_HEIGHT=100\npeer_require_source_ahead 192.0.2.2 100\n"])
    if same.returncode == 0 or "strictly ahead" not in same.stderr:
        _fail("recover.peer_pull.same_height", f"rc={same.returncode} err={same.stderr[-300:]}")
        return
    unknown = _run(["bash", "-c", script + "LOCAL_DIVERGED_HEIGHT=unknown\npeer_require_source_ahead 192.0.2.2 200\n"])
    if unknown.returncode == 0 or "local height unknown" not in unknown.stderr:
        _fail("recover.peer_pull.unknown_height", f"rc={unknown.returncode} err={unknown.stderr[-300:]}")
        return
    ahead = _run(["bash", "-c", script + "LOCAL_DIVERGED_HEIGHT=100\npeer_require_source_ahead 192.0.2.2 101\n"])
    if ahead.returncode != 0:
        _fail("recover.peer_pull.ahead_ok", f"rc={ahead.returncode} err={ahead.stderr[-300:]}")
        return
    _pass("recover.peer_pull.requires_peer_ahead")


def _test_watermark_never_lowers() -> None:
    """enable_validator_mode must not write a watermark below the one already on disk."""
    enable = os.path.join(REPO_ROOT, "deploy", "enable_validator_mode.sh")
    with tempfile.TemporaryDirectory(prefix="watermark-") as tmp:
        home = os.path.join(tmp, "home")
        node = os.path.join(home, ".mirage", "node")
        data = os.path.join(node, "data")
        os.makedirs(data, exist_ok=True)
        pv = os.path.join(data, "priv_validator_state.json")
        Path(pv).write_text('{"height": "1000", "round": 0, "step": 0}\n', encoding="utf-8")
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        status = json.dumps({"result": {"sync_info": {"catching_up": False, "latest_block_height": "12"}}})
        Path(os.path.join(bindir, "curl")).write_text(
            f"#!/bin/bash\nprintf '%s\\n' '{status}'\n",
            encoding="utf-8",
        )
        os.chmod(os.path.join(bindir, "curl"), 0o755)
        env = {**os.environ, "HOME": home, "PATH": bindir + ":" + os.environ.get("PATH", "")}
        r = _run(["bash", enable], env=env, timeout=20)
        if r.returncode != 0:
            _fail("install.watermark.lower_exit", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        kept = json.loads(Path(pv).read_text(encoding="utf-8"))
        if str(kept.get("height")) != "1000":
            _fail("install.watermark.lowered", f"height became {kept}")
            return
        if "refusing to lower" not in r.stdout:
            _fail("install.watermark.lower_message", r.stdout[-300:])
            return

        Path(pv).write_text('{"height": "500", "round": 0, "step": 0}\n', encoding="utf-8")
        catching = json.dumps({"result": {"sync_info": {"catching_up": True, "latest_block_height": "12"}}})
        Path(os.path.join(bindir, "curl")).write_text(
            f"#!/bin/bash\nprintf '%s\\n' '{catching}'\n",
            encoding="utf-8",
        )
        r = _run(["bash", enable], env=env, timeout=20)
        if r.returncode != 0:
            _fail("install.watermark.catching_exit", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        kept = json.loads(Path(pv).read_text(encoding="utf-8"))
        if str(kept.get("height")) != "500":
            _fail("install.watermark.catching_overwrote", f"height became {kept}")
            return
        if "catching_up" not in r.stdout:
            _fail("install.watermark.catching_message", r.stdout[-300:])
            return
    _pass("install.watermark.never_lowers")


def _test_weekly_restart_skips_catching_up() -> None:
    weekly = Path(REPO_ROOT, "deploy", "hosttools", "mirage-weekly-restart.sh").read_text(encoding="utf-8")
    idx_catch = weekly.find("catching up")
    idx_restart = weekly.find("docker restart")
    if idx_catch < 0 or idx_restart < 0 or idx_catch > idx_restart:
        _fail(
            "install.weekly.catching_up",
            "weekly restart does not skip catching_up before docker restart",
        )
        return
    _pass("install.weekly.skips_catching_up")


def _test_images_pruned_before_every_pull() -> None:
    """Reclaiming disk must precede the pull on every path that fetches an image.

    Pruning after the new container is up is too late to be worth anything: the
    transfer is what consumes the space. On 2026-08-20 a 2.2 GiB pull took val1
    to 100% mid-pull, CometBFT could not write its consensus WAL, and the
    validator stopped signing while the chain carried on. Both paths also used to
    guard the prune on the pruner being executable, so on any host that had never
    installed the host tools the cleanup was a silent no-op.
    """
    deploy = Path(REPO_ROOT, "deploy", "deploy.sh").read_text(encoding="utf-8")
    idx_prune = deploy.find("prune_mirage_images.sh")
    idx_transfer = deploy.find("Transferring image tarball")
    if idx_prune < 0 or idx_transfer < 0 or idx_prune > idx_transfer:
        _fail(
            "install.prune.deploy_before_transfer",
            "deploy.sh must prune before transferring the image, not after",
        )
        return
    # The pruner has to be shipped, not assumed: deploy.sh provisions hosts but
    # never installed the host tools.
    if "run_scp" not in deploy[:idx_transfer] or "prune_mirage_images.sh" not in deploy[:idx_transfer]:
        _fail("install.prune.deploy_ships_pruner", "deploy.sh must install the pruner before using it")
        return

    update = Path(REPO_ROOT, "deploy", "hosttools", "mirage-update").read_text(encoding="utf-8")
    if "reclaim_disk_for_pull" not in update:
        _fail("install.prune.update_reclaims", "mirage-update must reclaim disk before pulling")
        return
    for name in ("tick", "refresh_hosttools"):
        body = _shell_function(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-update"), name)
        idx_reclaim = body.find("reclaim_disk_for_pull")
        idx_pull = body.find("docker pull")
        if idx_reclaim < 0 or idx_pull < 0 or idx_reclaim > idx_pull:
            _fail(
                "install.prune.update_reclaims_first",
                f"mirage-update {name} pulls before reclaiming disk",
            )
            return
    # Activation is what makes the superseded release droppable: state.json only
    # names the new active and its rollback target once the swap is recorded.
    activate = _shell_function(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-update"), "activate_staged")
    if "prune_mirage_images.sh" not in activate:
        _fail("install.prune.update_prunes_on_activate", "activate_staged leaves the superseded image on disk")
        return

    # The only cleanup on a schedule rather than as a side-effect of deploying,
    # and it must run ahead of the early exits for a node that is down or syncing.
    weekly = Path(REPO_ROOT, "deploy", "hosttools", "mirage-weekly-restart.sh").read_text(encoding="utf-8")
    idx_prune = weekly.find("prune_mirage_images.sh")
    idx_exit = weekly.find("exit 1")
    if idx_prune < 0 or idx_exit < 0 or idx_prune > idx_exit:
        _fail(
            "install.prune.weekly_before_exit",
            "weekly restart must prune before it can exit early",
        )
        return
    # A node installed by the one-liner gets its weekly timer from
    # harden_server.sh, which writes its own copy of the script.
    harden = Path(REPO_ROOT, "deploy", "harden_server.sh").read_text(encoding="utf-8")
    if "prune_mirage_images.sh" not in harden:
        _fail(
            "install.prune.harden_weekly",
            "harden_server.sh weekly restart never prunes, so installer-provisioned hosts accumulate images",
        )
        return

    # Nothing may reclaim images without consulting the keep-list. `docker image
    # prune` cannot: Docker reports every untagged image as dangling, and a
    # digest pull is untagged, so a blanket prune deletes the rollback target and
    # the image armed for a governed halt. Behaviour is covered by
    # _test_prune_keeps_digest_pinned_images; this only keeps the blunt
    # instrument out of the paths that run unattended.
    for name in ("deploy/hosttools/prune_mirage_images.sh", "deploy/hosttools/mirage-update", "deploy/deploy.sh"):
        text = Path(REPO_ROOT, *name.split("/")).read_text(encoding="utf-8")
        # A comment warning against the command must not read as running it.
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        for blunt in ("docker image prune -f", "docker image prune -af", "docker image prune -a"):
            if blunt in code:
                _fail(
                    "install.prune.no_blanket_prune",
                    f"{name} runs '{blunt}', which ignores the keep-list and can delete a staged or halt-armed image",
                )
                return
    pruner = Path(REPO_ROOT, "deploy", "hosttools", "prune_mirage_images.sh").read_text(encoding="utf-8")
    if "RepoDigests" not in pruner:
        _fail(
            "install.prune.matches_digests",
            "pruner still identifies images by tag; digest-pinned pulls carry none, so it reclaims nothing",
        )
        return
    _pass("install.prune.before_every_pull")


def _test_moniker_update_pays_and_verifies() -> None:
    """A moniker that failed to change must not look like one that was already right.

    The moniker is what puts a node on /network, because the site list is built
    from the bonded validator set and a label like `mirage-node-3` names nowhere
    a visitor can go. The updater sent its transaction with no fee, so every run
    was rejected for insufficient fee, and it ended in `|| true` with output
    redirected to /dev/null, so every rejection was discarded and the deploy
    reported success. Two nodes kept their install-time labels and the page
    showed two servers while four were running.

    So: a fee, a fatal non-zero broadcast code, and confirmation from the chain.
    """
    path = Path(REPO_ROOT, "deploy", "update_moniker.sh")
    if not path.is_file():
        _fail("install.moniker.script_present", "deploy/update_moniker.sh is missing")
        return
    script = path.read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))

    if "--gas-prices" not in code:
        _fail(
            "install.moniker.pays_fee",
            "moniker update sends no fee, so the chain rejects it for insufficient fee",
        )
        return
    if "minimum-gas-prices" not in code:
        _fail(
            "install.moniker.fee_from_node_config",
            "gas price must come from the node's own app.toml, not a hardcoded guess",
        )
        return
    # Scoped to the broadcast: elsewhere a suppressed error can be deliberate,
    # but the transaction's own outcome is the thing that went missing.
    idx_tx = code.find("tx staking edit-validator")
    broadcast = code[idx_tx : code.find("\n\n", idx_tx)] if idx_tx >= 0 else ""
    if "|| true" in broadcast or "/dev/null" in broadcast:
        _fail(
            "install.moniker.does_not_swallow",
            "moniker update discards its own failure, which is how the stale monikers went unnoticed",
        )
        return
    if '.code // empty' not in code or 'CODE" != "0"' not in code:
        _fail(
            "install.moniker.checks_broadcast_code",
            "a rejected broadcast must be fatal, not ignored",
        )
        return
    # Accepted into the mempool is not committed, so the only real proof is the
    # chain reporting the new value.
    idx_broadcast = code.find("tx staking edit-validator")
    idx_confirm = code.rfind("current_moniker")
    if idx_broadcast < 0 or idx_confirm < idx_broadcast:
        _fail(
            "install.moniker.confirms_on_chain",
            "moniker update never re-reads the chain, so a dropped tx passes as success",
        )
        return

    # deploy.sh must actually use it, and must not keep its own inline copy.
    deploy = Path(REPO_ROOT, "deploy", "deploy.sh").read_text(encoding="utf-8")
    if "deploy/update_moniker.sh" not in deploy:
        _fail("install.moniker.deploy_uses_script", "deploy.sh does not run update_moniker.sh")
        return
    if "MONIKER_UPDATE_SCRIPT" in deploy:
        _fail(
            "install.moniker.no_inline_copy",
            "deploy.sh still carries an inline moniker updater that can drift from the script",
        )
        return
    _pass("install.moniker.pays_and_verifies")


def _test_prune_keeps_digest_pinned_images() -> None:
    """The keep-list must survive the fact that release images carry no tag.

    Both deploy.sh and mirage-update pull by digest, and a digest pull leaves
    RepoTags empty. That broke the pruner in both directions: a sweep reading
    only {{.Repository}}:{{.Tag}} matched no release image at all, and
    `docker image prune -f` matched every one of them, because Docker calls any
    untagged image dangling and prune never consults the keep-list. The second
    is the dangerous one -- it deletes the rollback target, a staged release,
    and the image armed for a governed halt, which strands the upgrade.
    """
    pruner = os.path.join(REPO_ROOT, "deploy", "hosttools", "prune_mirage_images.sh")
    repo = "ghcr.io/miragefoundation/mirage-node"
    # Distinct digests standing in for each role the keep-list protects.
    ids = {
        "active": "sha256:" + "a" * 64,
        "previous": "sha256:" + "b" * 64,
        "staged": "sha256:" + "c" * 64,
        "prepared": "sha256:" + "d" * 64,
        "obsolete": "sha256:" + "e" * 64,
        "orphan": "sha256:" + "f" * 64,
        "foreign": "sha256:" + "1" * 64,
    }
    repo_digest = {role: f"{repo}@sha256:{role_id[7:]}" for role, role_id in ids.items()}

    with tempfile.TemporaryDirectory(prefix="prune-keep-") as tmp:
        home = os.path.join(tmp, "home")
        os.makedirs(os.path.join(home, ".mirage", "upgrade"), exist_ok=True)
        state_file = os.path.join(tmp, "state.json")
        Path(state_file).write_text(
            json.dumps(
                {
                    "active": repo_digest["active"],
                    "previous": repo_digest["previous"],
                    "staged": repo_digest["staged"],
                }
            ),
            encoding="utf-8",
        )
        Path(os.path.join(home, ".mirage", "upgrade", "prepared.json")).write_text(
            json.dumps({"image": repo_digest["prepared"]}), encoding="utf-8"
        )

        removed = os.path.join(tmp, "removed.txt")
        # Every release image is untagged, exactly as a digest pull leaves it.
        # 'orphan' has neither tag nor digest (an interrupted pull) and must go;
        # 'foreign' is another project's tagged image and must be left alone.
        tags = {role: "" for role in ids}
        tags["foreign"] = "postgres:16-alpine"
        digests = {role: repo_digest[role] for role in ids}
        digests["orphan"] = ""
        digests["foreign"] = "postgres@sha256:" + "1" * 64

        by_id = {ids[role]: role for role in ids}
        stub = f"""#!/usr/bin/env python3
import sys
TAGS = {tags!r}
DIGESTS = {digests!r}
BY_ID = {by_id!r}
IDS = {list(ids.values())!r}
a = sys.argv[1:]
if a[:2] == ["inspect", "mirage"]:
    print({ids["active"]!r})
elif a[0] == "images":
    print("\\n".join(IDS))
elif a[:2] == ["image", "inspect"]:
    role = BY_ID[a[2]]
    print(TAGS[role] if "RepoTags" in a[-1] else DIGESTS[role])
elif a[0] == "rmi":
    open({removed!r}, "a").write(BY_ID[a[1]] + "\\n")
else:
    sys.exit(1)
"""
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir, exist_ok=True)
        docker = os.path.join(bindir, "docker")
        Path(docker).write_text(stub, encoding="utf-8")
        os.chmod(docker, 0o755)

        env = {
            **os.environ,
            "HOME": home,
            "MIRAGE_UPDATE_STATE_FILE": state_file,
            "PATH": bindir + os.pathsep + os.environ.get("PATH", ""),
        }
        result = _run(["bash", pruner], env=env, timeout=60)
        if result.returncode != 0:
            _fail("install.prune.keep_exit", f"rc={result.returncode} err={result.stderr[-400:]}")
            return

        gone = set(Path(removed).read_text(encoding="utf-8").split()) if os.path.isfile(removed) else set()
        for role in ("active", "previous", "staged", "prepared"):
            if role in gone:
                _fail(
                    "install.prune.keep_protected",
                    f"pruner deleted the {role} image; a digest pull is untagged, not disposable",
                )
                return
        if "foreign" in gone:
            _fail("install.prune.keep_foreign", "pruner deleted an unrelated project's image")
            return
        for role in ("obsolete", "orphan"):
            if role not in gone:
                _fail(
                    "install.prune.reclaims",
                    f"pruner kept the {role} image, so nothing is reclaimed and disks still fill",
                )
                return
    _pass("install.prune.keeps_digest_pinned")


def _test_stake_floor_and_lock() -> None:
    stake_body = Path(STAKE_PY).read_text(encoding="utf-8")
    if '"--unordered"' not in stake_body or '"--timeout-duration"' not in stake_body:
        _fail("install.stake.unordered", "stake transaction is not unordered")
        return
    with tempfile.TemporaryDirectory(prefix="stake-") as tmp:
        home = os.path.join(tmp, ".mirage")
        os.makedirs(os.path.join(home, "env"), exist_ok=True)
        manifest = {
            "min_liquid_umirage": "1000000000000",
            "self_delegation_umirage": "5000000000000",
            "activation_balance_umirage": "10000000000000",
            "chain_id": "mirage-1",
            "genesis_sha256": "79eb6a81a83707cfd34f69e6f17bf6006ffa9f521b130f51dded92e04c6cfc8d",
            "rpc": ["http://a", "http://b"],
            "rest": ["http://a", "http://b"],
            "api": ["http://a", "http://b"],
        }
        Path(os.path.join(home, "env", "network-manifest.json")).write_text(json.dumps(manifest), encoding="utf-8")
        env = {**os.environ, "HOME": tmp}
        r = _run(["python3", STAKE_PY, "--stake-all-above", "999999", "--yes"], env=env)
        if r.returncode == 0:
            _fail("install.stake.argparse_floor", "accepted --stake-all-above below the floor")
            return
        err = (r.stderr or "") + (r.stdout or "")
        if "1000000" not in err.replace(",", "") and "1,000,000" not in err:
            _fail("install.stake.argparse_floor_msg", f"unexpected: {err[-300:]}")
            return
        _pass("install.stake.refuses_below_floor")

        lock_path = os.path.join(home, "stake.lock")
        os.makedirs(home, exist_ok=True)
        with open(lock_path, "a+") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = _run(["python3", STAKE_PY, "--stake-all-above", "1000000", "--yes"], env=env)
        if r.returncode == 0:
            _fail("install.stake.lock", "second stake.py ran while the lock was held")
            return
        err = (r.stderr or "") + (r.stdout or "")
        if "already running" not in err:
            _fail("install.stake.lock_msg", f"unexpected: {err[-300:]}")
            return
        _pass("install.stake.flock")


def _test_economics_single_source() -> None:
    net = json.loads(Path(NETWORK_JSON).read_text(encoding="utf-8"))
    for key in (
        "activation_balance_umirage",
        "self_delegation_umirage",
        "min_liquid_umirage",
    ):
        if key not in net:
            _fail("install.economics.manifest_keys", f"missing {key}")
            return
    if net["min_liquid_umirage"] != "1000000000000":
        _fail("install.economics.min_liquid", f"{net['min_liquid_umirage']}")
        return
    if net["activation_balance_umirage"] != "10000000000000":
        _fail("install.economics.activation", f"{net['activation_balance_umirage']}")
        return
    if net["self_delegation_umirage"] != "5000000000000":
        _fail("install.economics.self_delegation", f"{net['self_delegation_umirage']}")
        return
    create_body = Path(CREATE_VALIDATOR).read_text(encoding="utf-8")
    stake_body = Path(STAKE_PY).read_text(encoding="utf-8")
    dash_body = Path(os.path.join(REPO_ROOT, "scripts", "status_dashboard.py")).read_text(encoding="utf-8")
    for label, body in (
        ("create_validator", create_body),
        ("stake", stake_body),
        ("dashboard", dash_body),
    ):
        if "min_liquid_umirage" not in body and "self_delegation_umirage" not in body:
            _fail("install.economics.consumers", f"{label} does not read the network manifest")
            return
    _pass("install.economics.single_source")


def _test_mint_floor_backend_required() -> None:
    """The backend must reject an indexer row that predates field 55."""
    source_path = Path(REPO_ROOT, "web", "backend", "params.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    required_float_params = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "_REQUIRED_FLOAT_PARAMS" for target in node.targets):
            required_float_params = ast.literal_eval(node.value)
            break
    if required_float_params is None:
        _fail("install.params.mint_floor_required", "_REQUIRED_FLOAT_PARAMS assignment is missing")
        return
    if "mint_floor_split" not in required_float_params:
        _fail("install.params.mint_floor_required", f"required floats={required_float_params!r}")
        return
    _pass("install.params.mint_floor_required")


def _test_caddy_well_known() -> None:
    caddy = Path(REPO_ROOT, "deploy", "templates", "caddy", "Caddyfile").read_text(encoding="utf-8")
    idx_well = caddy.find("handle /.well-known/mirage/*")
    idx_spa = caddy.find("\thandle {\n\t\troot * /opt/mirage/web/frontend/build")
    if idx_well < 0:
        _fail("install.caddy.well_known", "missing /.well-known/mirage handle")
        return
    if idx_spa < 0 or idx_well > idx_spa:
        _fail("install.caddy.well_known_order", "well-known handle must precede the SPA catch-all")
        return
    entry = Path(REPO_ROOT, "deploy", "entrypoint.sh").read_text(encoding="utf-8")
    if "/root/.mirage/well-known" not in entry:
        _fail("install.entrypoint.well_known", "entrypoint does not populate well-known")
        return
    for name in ("manifest.json.sig", "network.json.sig", "harden_server.sh", "release_verify.py"):
        if name not in entry:
            _fail("install.entrypoint.mirror_complete", f"well-known mirror does not publish {name}")
            return
    _pass("install.caddy.well_known_before_spa")


def _test_unjail_tool() -> None:
    """Unjailing is the operator's job after any outage, so it is a host tool.

    Two properties matter beyond it existing. It must refuse while the node is
    catching up, because a validator that is not signing yet is jailed again on
    the next window. And it must not carry a second copy of the transaction
    logic: sequence handling and state-based confirmation live in the container
    script, which is the only place they should live.
    """
    tool = Path(REPO_ROOT, "deploy", "hosttools", "mirage-unjail")
    if not tool.exists():
        _fail("install.unjail.exists", "deploy/hosttools/mirage-unjail is missing")
        return
    body = tool.read_text(encoding="utf-8")
    if "catching_up" not in body:
        _fail("install.unjail.sync_guard", "does not refuse while the node is catching up")
        return
    if "unjail_validator.sh" not in body:
        _fail("install.unjail.delegates", "does not delegate the transaction to the container script")
        return
    if "tx slashing unjail" in body:
        _fail("install.unjail.duplicate_tx", "builds its own unjail transaction instead of delegating")
        return

    # Installed by both paths, or a node gets the tool only on a fresh install.
    for name, path in (("install.sh", INSTALL_SH), ("mirage-update", UPDATE_SH)):
        text = Path(path).read_text(encoding="utf-8")
        if "mirage-unjail" not in text:
            _fail("install.unjail.installed", f"{name} does not install mirage-unjail")
            return

    script = Path(REPO_ROOT, "scripts", "unjail_validator.sh").read_text(encoding="utf-8")
    # The jail terms have to come from this validator's own signing info. Reading
    # the chain-wide list and guessing which entry is ours misreports jailed_until
    # as soon as a second validator is jailed, which is exactly when an outage
    # makes this needed.
    if "signing-info" not in script or "consensus_pubkey.value" not in script:
        _fail("install.unjail.signing_info", "does not resolve signing info from the validator's own pubkey")
        return
    for guess in ("heuristic", "Using first jailed signing-info", "MOST_RECENT"):
        if guess in script:
            _fail("install.unjail.no_guessing", f"still guesses which signing-info is ours ({guess!r})")
            return
    if "tombstoned" not in script:
        _fail("install.unjail.tombstoned", "does not check for tombstoning before submitting")
        return
    _pass("install.unjail_tool")


def _test_stale_chunk_recovery() -> None:
    """A deploy renames every chunk, so a browser on the previous build asks for
    files the origin no longer has. Two things went wrong when that happened:
    the SPA catch-all answered those asset requests with 200 index.html, which
    the browser rejects as a text/html module, and the client-side reload that
    exists to recover matched only Chrome's failure wording, so Firefox and
    Safari sat on a blank route. Either one alone breaks the page.
    """
    caddy = Path(REPO_ROOT, "deploy", "templates", "caddy", "Caddyfile").read_text(encoding="utf-8")
    idx_404 = caddy.find("respond @missing_asset 404")
    idx_try = caddy.find("try_files {path} /index.html")
    if idx_404 < 0:
        _fail("install.caddy.missing_asset_404", "no 404 for a missing /static/* asset")
        return
    if idx_try < 0 or idx_404 > idx_try:
        _fail("install.caddy.missing_asset_order", "the 404 must be reached before the SPA fallback")
        return
    matcher = caddy[caddy.find("@missing_asset", 0) : idx_404]
    if "path /static/*" not in matcher or "not file" not in matcher:
        _fail("install.caddy.missing_asset_matcher", f"matcher does not scope to absent /static/*: {matcher!r}")
        return

    app = Path(REPO_ROOT, "web", "frontend", "src", "App.js").read_text(encoding="utf-8")
    start = app.find("function lazyWithRetry(")
    if start < 0:
        _fail("install.frontend.lazy_retry", "lazyWithRetry is gone")
        return
    body = app[start : app.find("\nconst MainView", start)]
    if "window.location.reload()" not in body:
        _fail("install.frontend.lazy_retry_reload", "a failed chunk import no longer reloads")
        return
    # Firefox says "error loading dynamically imported module" and Safari says
    # "Importing a module script failed". Any per-browser string here means the
    # browsers not on the list stay broken, which is the bug this covers.
    for prose in ("Failed to fetch dynamically imported module", "Loading chunk", "ChunkLoadError"):
        if prose in body:
            _fail("install.frontend.lazy_retry_sniffing", f"recovery gated on browser-specific text {prose!r}")
            return
    if "removeItem(CHUNK_RELOAD_KEY)" not in app:
        _fail("install.frontend.lazy_retry_rearm", "the once-per-tab guard is never cleared after a good load")
        return
    _pass("install.stale_chunk_recovery")


def _test_caddy_csp_upgrade_scoped_to_tls() -> None:
    """A node reached by IP must not send upgrade-insecure-requests.

    It serves :80 and cannot hold a cert for an IP, so the upgrade rewrites the
    module script to https://<ip>/static/js/index.*.js, nothing answers on 443,
    and the browser gets a blank app instead of the site.
    """
    template = Path(REPO_ROOT, "deploy", "templates", "caddy", "Caddyfile")
    body = template.read_text(encoding="utf-8")
    if "manifest-src 'self'${CSP_UPGRADE_INSECURE}" not in body:
        _fail("install.caddy.csp_upgrade_templated", "CSP does not end in ${CSP_UPGRADE_INSECURE}")
        return

    entry = Path(REPO_ROOT, "deploy", "entrypoint.sh").read_text(encoding="utf-8")
    if 'export CSP_UPGRADE_INSECURE="; upgrade-insecure-requests"' not in entry:
        _fail("install.entrypoint.csp_upgrade_export", "entrypoint does not set the directive for a domain")
        return
    # An unset variable renders empty, so a domain node would lose the directive
    # silently without a startup guard. Reuse the entrypoint's own pattern so the
    # render below is judged exactly as the running node judges it: a comment
    # naming the directive must neither satisfy nor trip it.
    guard = re.search(r"^CSP_UPGRADE_RENDERED='([^']+)'$", entry, re.M)
    if not guard:
        _fail("install.entrypoint.csp_guard", "entrypoint does not verify the rendered directive")
        return
    pattern = re.compile(guard.group(1))

    renderer = os.path.join(REPO_ROOT, "deploy", "render_template.py")
    with tempfile.TemporaryDirectory() as tmp:
        for label, value, want in (
            ("domain", "; upgrade-insecure-requests", True),
            ("ip_only", "", False),
        ):
            out = os.path.join(tmp, f"Caddyfile.{label}")
            env = dict(os.environ, CSP_UPGRADE_INSECURE=value)
            result = _run(["python3", renderer, str(template), out], env=env)
            if result.returncode != 0:
                _fail(f"install.caddy.csp_render_{label}", result.stderr[-300:])
                return
            got = bool(pattern.search(Path(out).read_text(encoding="utf-8")))
            if got != want:
                _fail(
                    f"install.caddy.csp_upgrade_{label}",
                    f"upgrade-insecure-requests present={got}, expected {want}",
                )
                return

    # setup_letsencrypt.py renders the same template on the HTTPS path, where the
    # directive must always survive.
    tls = Path(REPO_ROOT, "deploy", "setup_letsencrypt.py").read_text(encoding="utf-8")
    if 'os.environ["CSP_UPGRADE_INSECURE"] = "; upgrade-insecure-requests"' not in tls:
        _fail("install.letsencrypt.csp_upgrade_set", "HTTPS setup renders without the directive")
        return
    if "lost upgrade-insecure-requests" not in tls:
        _fail("install.letsencrypt.csp_upgrade_verified", "HTTPS setup does not verify the rendered policy")
        return
    _pass("install.caddy.csp_upgrade_scoped_to_tls")


def _test_repodigest_pin() -> None:
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    update = Path(REPO_ROOT, "deploy", "hosttools", "mirage-update").read_text(encoding="utf-8")
    if "RepoDigest" not in install or "RepoDigest" not in update:
        _fail("install.repodigest", "installer/updater must refuse a RepoDigest mismatch")
        return
    _pass("install.repodigest_pin")


def _replacement_confirm_script(tmp: str, answer: str, rpc_status: str | None = None) -> str:
    answer_path = os.path.join(tmp, "answer")
    Path(answer_path).write_text(answer, encoding="utf-8")
    manifest_dir = os.path.join(tmp, "manifests")
    os.makedirs(manifest_dir, exist_ok=True)
    replacement = os.path.join(tmp, "replacement.json")
    function = _shell_function(INSTALL_SH, "confirm_validator_replacement")
    function = function.replace("[[ ! -t 1 ]] || ! : </dev/tty 2>/dev/null", "false")
    function = function.replace("read -r confirm </dev/tty", f"read -r confirm < {answer_path!r}")
    curl_body = (
        rpc_status or '{"result":{"node_info":{"network":"mirage-1"},"sync_info":{"latest_block_height":"1000"}}}'
    )
    return f"""set -euo pipefail
REPLACEMENT_FILE={replacement!r}
MANIFEST_DIR={manifest_dir!r}
die() {{ echo "ERROR: $*" >&2; exit 1; }}
curl() {{
  printf '%s\\n' {curl_body!r}
  return 0
}}
{function}
confirm_validator_replacement TARGETPUB miragevaloper1existing
"""


def _test_validator_replacement() -> None:
    """Seed-only replacement requires an exact token, live RPC heights, and a monotonic watermark."""
    installer = Path(INSTALL_SH).read_text(encoding="utf-8")
    if "MIRAGE_REPLACE" in installer or "confirm_validator_replacement" not in installer:
        _fail("install.replace.env_bypass", "replacement must not be bypassable by environment")
        return
    collision = _shell_function(INSTALL_SH, "collision_guard")
    if 'local_pub" == "$pub"' not in collision or "reinstall is idempotent" not in collision:
        _fail("install.replace.same_host", "same-host reinstall must skip the replace prompt")
        return
    init = Path(os.path.join(REPO_ROOT, "deploy", "init.sh")).read_text(encoding="utf-8")
    if "Restored consensus watermark" not in init or "refusing to lower" not in init:
        _fail("install.replace.init_watermark", "init.sh must not let miraged init lower a replacement watermark")
        return

    with tempfile.TemporaryDirectory(prefix="replace-refuse-") as tmp:
        Path(os.path.join(tmp, "manifests", "network.json")).parent.mkdir(parents=True)
        Path(os.path.join(tmp, "manifests", "network.json")).write_text(
            json.dumps({"rpc": ["http://127.0.0.1:26657", "http://127.0.0.1:26658"]}),
            encoding="utf-8",
        )
        for answer, label in (("", "blank"), ("Replace", "case"), ("yes", "other"), ("", "eof")):
            script = _replacement_confirm_script(tmp, answer)
            if label == "eof":
                Path(os.path.join(tmp, "answer")).write_text("", encoding="utf-8")
            r = _run(["bash", "-c", script])
            replacement = os.path.join(tmp, "replacement.json")
            if r.returncode == 0 or os.path.isfile(replacement) or "replacement not confirmed" not in (r.stderr or ""):
                _fail(
                    f"install.replace.refuse_{label}",
                    f"rc={r.returncode} err={r.stderr} exists={os.path.isfile(replacement)}",
                )
                return

    with tempfile.TemporaryDirectory(prefix="replace-ok-") as tmp:
        Path(os.path.join(tmp, "manifests")).mkdir()
        Path(os.path.join(tmp, "manifests", "network.json")).write_text(
            json.dumps({"rpc": ["http://one.example", "http://two.example"]}),
            encoding="utf-8",
        )
        script = _replacement_confirm_script(
            tmp,
            "replace",
            '{"result":{"node_info":{"network":"mirage-1"},"sync_info":{"latest_block_height":"4242"}}}',
        )
        r = _run(["bash", "-c", script])
        replacement = os.path.join(tmp, "replacement.json")
        if r.returncode != 0 or not os.path.isfile(replacement):
            _fail("install.replace.confirm", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        state = json.loads(Path(replacement).read_text(encoding="utf-8"))
        if state.get("watermark") != 4252 or state.get("consensus_pubkey") != "TARGETPUB":
            _fail("install.replace.watermark", f"state={state}")
            return
        r2 = _run(["bash", "-c", script])
        if r2.returncode != 0 or "already confirmed" not in (r2.stdout or ""):
            _fail("install.replace.resume", f"rc={r2.returncode} out={r2.stdout} err={r2.stderr}")
            return

    with tempfile.TemporaryDirectory(prefix="replace-rpc-") as tmp:
        Path(os.path.join(tmp, "manifests")).mkdir()
        Path(os.path.join(tmp, "manifests", "network.json")).write_text(
            json.dumps({"rpc": ["http://one.example", "http://two.example"]}),
            encoding="utf-8",
        )
        script = _replacement_confirm_script(
            tmp,
            "replace",
            '{"result":{"node_info":{"network":"not-mirage"},"sync_info":{"latest_block_height":"9"}}}',
        )
        r = _run(["bash", "-c", script])
        if r.returncode == 0 or "expected mirage-1" not in (r.stderr or ""):
            _fail("install.replace.chain_id", f"rc={r.returncode} err={r.stderr}")
            return

    with tempfile.TemporaryDirectory(prefix="replace-apply-") as tmp:
        dest_root = os.path.join(tmp, "host")
        data = os.path.join(dest_root, "node", "data")
        os.makedirs(data, exist_ok=True)
        os.makedirs(os.path.join(dest_root, "node", "config"), exist_ok=True)
        Path(os.path.join(dest_root, "node", "config", "node_key.json")).write_text("old-p2p\n", encoding="utf-8")
        os.makedirs(os.path.join(data, "application.db"), exist_ok=True)
        Path(os.path.join(data, "application.db", "CURRENT")).write_text("x\n", encoding="utf-8")
        replacement = os.path.join(tmp, "replacement.json")
        Path(replacement).write_text(
            json.dumps({"watermark": 9000, "consensus_pubkey": "P"}),
            encoding="utf-8",
        )
        function = _shell_function(INSTALL_SH, "apply_replacement_watermark").replace("/root/.mirage", dest_root)
        script = f"""set -euo pipefail
REPLACEMENT_FILE={replacement!r}
die() {{ echo "ERROR: $*" >&2; exit 1; }}
{function}
apply_replacement_watermark
"""
        r = _run(["bash", "-c", script])
        pv = os.path.join(data, "priv_validator_state.json")
        if r.returncode != 0 or not os.path.isfile(pv):
            _fail("install.replace.apply", f"rc={r.returncode} err={r.stderr}")
            return
        written = json.loads(Path(pv).read_text(encoding="utf-8"))
        if str(written.get("height")) != "9000":
            _fail("install.replace.apply_height", written)
            return
        if os.path.exists(os.path.join(dest_root, "node", "config", "node_key.json")):
            _fail("install.replace.fresh_p2p", "replacement left the old P2P identity on disk")
            return
        if os.path.exists(os.path.join(data, "application.db")):
            _fail("install.replace.empty_chain_db", "replacement left chain databases on disk")
            return
        Path(pv).write_text(json.dumps({"height": "12000", "round": 0, "step": 0}) + "\n", encoding="utf-8")
        r = _run(["bash", "-c", script])
        kept = json.loads(Path(pv).read_text(encoding="utf-8"))
        if r.returncode != 0 or str(kept.get("height")) != "12000":
            _fail("install.replace.apply_monotonic", f"rc={r.returncode} kept={kept} err={r.stderr}")
            return
        if "will not lower" not in (r.stdout or ""):
            _fail("install.replace.apply_message", r.stdout)
            return
    _pass("install.replace.confirmation_and_watermark")


def _test_governed_upgrade_prepare() -> None:
    """Only explicit preparation fetches upgrades; halt activation uses the prepared image."""
    updater = Path(UPDATE_SH).read_text(encoding="utf-8")
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    systemd_dir = os.path.join(REPO_ROOT, "deploy", "hosttools", "systemd")
    for legacy_unit in ("mirage-update.service", "mirage-update.timer"):
        unit = Path(systemd_dir, legacy_unit).read_text(encoding="utf-8")
        if "ConditionPathExists=/var/lib/mirage/update/automatic-fetch-enabled" not in unit or "--tick" in unit:
            _fail("install.upgrade.background_fetch_unit", f"{legacy_unit} is not an inert compatibility stub")
            return
    if "enable --now mirage-update.timer" in install:
        _fail("install.upgrade.background_fetch_enabled", "installer enables automatic release fetching")
        return
    if "disable --now mirage-update.timer" not in install or "disable --now mirage-update.timer" not in updater:
        _fail("install.upgrade.legacy_fetch_timer", "existing automatic release timer is not disabled")
        return
    wrapper = Path(os.path.join(REPO_ROOT, "deploy", "run_miraged_supervised.sh")).read_text(encoding="utf-8")
    timer = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "systemd", "mirage-upgrade-activate.timer")).read_text(
        encoding="utf-8"
    )
    service = Path(
        os.path.join(REPO_ROOT, "deploy", "hosttools", "systemd", "mirage-upgrade-activate.service")
    ).read_text(encoding="utf-8")
    if "OnUnitActiveSec=30s" not in timer or "--activate-if-halted" not in service:
        _fail("install.upgrade.timer", "activation timer is missing or does not invoke --activate-if-halted")
        return
    if "hold_for_governed_upgrade" not in wrapper or "no prepared.json staged" not in wrapper:
        _fail("install.upgrade.hold", "node wrapper must hold at the halt without burning restart budget")
        return
    if "autorestart=unexpected does not relaunch" not in wrapper:
        _fail("install.upgrade.budget_exit", "node wrapper must exit 0 when the hourly restart budget is exhausted")
        return
    # CometBFT wraps the halt in an err="..." payload that escapes the inner
    # quotes. A pattern needing a bare quote misses the real production line, the
    # halt goes undetected, and the pre-upgrade binary restart-loops at the halt
    # height. Assert against both shapes rather than against the pattern text.
    halt_pattern = _shell_variable(
        os.path.join(REPO_ROOT, "deploy", "run_miraged_supervised.sh"), "UPGRADE_HALT_PATTERN"
    )
    if not halt_pattern:
        _fail("install.upgrade.halt_pattern", "node wrapper has no UPGRADE_HALT_PATTERN to check")
        return
    escaped = (
        'ERR CONSENSUS FAILURE!!! err="failed to apply block; error UPGRADE \\"v1.26.0\\" NEEDED at height: 4895581: "'
    )
    for label, line, want in (
        ("escaped", escaped, True),
        ("plain", 'ERR UPGRADE "v1.26.0" NEEDED at height: 4895581', True),
        ("apphash", 'ERR CONSENSUS FAILURE!!! err="wrong Block.Header.AppHash"', False),
        ("unquoted", "INFO UPGRADE scheduled NEEDED at height: 5", False),
    ):
        with tempfile.TemporaryDirectory(prefix="halt-line-") as tmp:
            log = os.path.join(tmp, "node.log")
            Path(log).write_text(line + "\n", encoding="utf-8")
            # Pass the pattern as argv: shell-quoting it inline would alter its
            # backslashes and silently test a different pattern than ships.
            probe = _run(["bash", "-c", 'grep -aE "$1" "$2" >/dev/null', "bash", halt_pattern, log])
            if (probe.returncode == 0) is not want:
                _fail(
                    "install.upgrade.halt_line",
                    f"{label} halt line: matched={probe.returncode == 0}, expected {want}",
                )
                return
    if "hold_for_governed_upgrade" not in wrapper:
        _fail("install.upgrade.halt_line_wired", "halt detection is not wired to the hold")
        return

    # The scan must see only the run that just exited. Reading the whole day's
    # file matches halts from earlier runs that were already resolved: on
    # 2026-08-20 every validator exited on an unrelated invariant fault at 15:01
    # while that day's log still held a v1.38.0 halt from 01:02, so each one held
    # for an upgrade that had already happened, never restarted, and reported the
    # wrong cause for a fleet-wide outage.
    if "mark_run_start" not in wrapper:
        _fail("install.upgrade.halt_scan_scoped", "node wrapper does not mark where the current run's output begins")
        return
    wrapper_path = os.path.join(REPO_ROOT, "deploy", "run_miraged_supervised.sh")
    halt_funcs = _shell_function(wrapper_path, "current_run_output") + _shell_function(
        wrapper_path, "upgrade_halt_detected"
    )
    stale = escaped + "\n"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for label, appended, want in (
        ("stale_halt_from_earlier_run", "FATAL: supply delta invariant violated for umirage\n", False),
        ("halt_in_this_run", escaped + "\n", True),
    ):
        with tempfile.TemporaryDirectory(prefix="halt-scope-") as tmp:
            os.makedirs(os.path.join(tmp, "node"))
            log = os.path.join(tmp, "node", f"miraged-{today}.log")
            Path(log).write_text(stale, encoding="utf-8")
            offset = len(stale.encode("utf-8"))
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(appended)
            harness = (
                "set -uo pipefail\n"
                'LOGS_DIR="$1"; RUN_LOG_DATE="$2"; RUN_LOG_OFFSET="$3"; UPGRADE_HALT_PATTERN="$4"\n'
                f"{halt_funcs}"
                'line="$(upgrade_halt_detected || true)"\n'
                '[ -n "$line" ]\n'
            )
            probe = _run(["bash", "-c", harness, "bash", tmp, today, str(offset), halt_pattern])
            if (probe.returncode == 0) is not want:
                _fail(
                    "install.upgrade.halt_scan_scoped",
                    f"{label}: detected={probe.returncode == 0}, expected {want}",
                )
                return
    _pass("install.upgrade.halt_scan_scoped")

    # A node stopped by a consensus fault has no RPC and, if it is a validator,
    # a non-zero signed height. Refusing there meant the updater declined to
    # update exactly the nodes that a new image would rescue: on 2026-08-20 the
    # validators halted at 6969190 could not run mirage-update at all.
    activate_src = _shell_function(UPDATE_SH, "activate_staged")
    if "refusing activation after signed height" in activate_src:
        _fail(
            "install.update.halted_node_can_activate",
            "activate_staged still refuses when the node is down and has signed",
        )
        return
    # The live-RPC protection must survive: recreating mid-sync discards it.
    if "node is catching up; refusing activation" not in activate_src:
        _fail("install.update.catching_up_still_guarded", "mid-sync activation is no longer refused")
        return

    pruner = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "prune_mirage_images.sh")).read_text(encoding="utf-8")
    if "prepared.json" not in pruner:
        _fail("install.upgrade.prune_keeps_prepared", "image pruner can delete the image armed for a governed halt")
        return

    prepare = _shell_function(UPGRADE_SH, "prepare")
    arm = _shell_function(UPGRADE_SH, "arm_governed_upgrade")
    activate = _shell_function(UPDATE_SH, "activate_if_halted")
    idx_disable = prepare.find("disable_automatic_release_fetch")
    idx_tick = prepare.find("tick")
    if idx_disable < 0 or idx_tick < idx_disable or prepare.find("arm_governed_upgrade") < idx_tick:
        _fail(
            "install.upgrade.prepare_sequence", "mirage-upgrade must disable background fetching before fetch and arm"
        )
        return

    def _arm_harness(tmp: str, activation: str, plan: str, upgrade_name: str = "v-test") -> tuple[str, str]:
        """Build a shell preamble whose stubbed tick installs the release manifest."""
        home = os.path.join(tmp, "home")
        work = os.path.join(tmp, "work")
        os.makedirs(os.path.join(home, ".mirage", "env"), exist_ok=True)
        os.makedirs(work, exist_ok=True)
        release = os.path.join(tmp, "release.json")
        Path(release).write_text(
            json.dumps(
                {
                    "activation": activation,
                    "upgrade_name": upgrade_name,
                    "image": "ghcr.io/miragefoundation/mirage-node@sha256:" + ("b" * 64),
                    "release_id": 9,
                }
            ),
            encoding="utf-8",
        )
        installed = os.path.join(home, ".mirage", "env", "release-manifest.json")
        preamble = f"""set -euo pipefail
HOME={home!r}
tmp={work!r}
MANIFEST_URL=release
NETWORK_URL=network
STATE_DIR={os.path.join(tmp, "state")!r}
mkdir -p "$STATE_DIR"
fetch_verify() {{ cp {release!r} "$2"; }}
json_field() {{ python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }}
tick() {{ cp {release!r} {installed!r}; }}
systemctl() {{ :; }}
disable_automatic_release_fetch() {{ :; }}
curl() {{
  printf '%s\\n' {plan!r}
  return 0
}}
query_local_rest() {{ curl "$@"; }}
{arm}
{prepare}
"""
        return preamble, os.path.join(home, ".mirage", "upgrade", "prepared.json")

    with tempfile.TemporaryDirectory(prefix="prepare-ordinary-") as tmp:
        preamble, _ = _arm_harness(tmp, "ordinary", '{"plan":{"name":"v-test","height":"10"}}')
        r = _run(["bash", "-c", preamble + "prepare\n"])
        if r.returncode == 0 or "upgrade-halt" not in (r.stderr or ""):
            _fail("install.upgrade.prepare_ordinary", f"rc={r.returncode} err={r.stderr}")
            return

    with tempfile.TemporaryDirectory(prefix="prepare-noplan-") as tmp:
        preamble, prepared_path = _arm_harness(tmp, "upgrade-halt", '{"plan":null}')
        r = _run(["bash", "-c", preamble + "prepare\n"])
        if r.returncode != 0 or "prepared v-test before governance" not in (r.stdout or ""):
            _fail("install.upgrade.prepare_before_proposal", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        prepared = json.loads(Path(prepared_path).read_text(encoding="utf-8"))
        if prepared.get("plan_height") != 0:
            _fail("install.upgrade.prepare_pending_height", prepared)
            return

    with tempfile.TemporaryDirectory(prefix="prepare-mismatch-") as tmp:
        preamble, _ = _arm_harness(tmp, "upgrade-halt", '{"plan":{"name":"other","height":"99"}}', "v-test")
        r = _run(["bash", "-c", preamble + "prepare\n"])
        if r.returncode == 0 or "does not match" not in (r.stderr or ""):
            _fail("install.upgrade.prepare_mismatch", f"rc={r.returncode} err={r.stderr}")
            return

    with tempfile.TemporaryDirectory(prefix="prepare-arms-") as tmp:
        preamble, prepared_path = _arm_harness(tmp, "upgrade-halt", '{"plan":{"name":"v-test","height":"4242"}}')
        r = _run(["bash", "-c", preamble + "prepare\n"])
        if r.returncode != 0 or not os.path.isfile(prepared_path):
            _fail("install.upgrade.prepare_arms", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        armed = json.loads(Path(prepared_path).read_text(encoding="utf-8"))
        if armed.get("upgrade_name") != "v-test" or armed.get("plan_height") != 4242:
            _fail("install.upgrade.prepare_arms_payload", armed)
            return
        again = _run(["bash", "-c", preamble + "prepare\n"])
        if again.returncode != 0 or "already armed" not in (again.stdout or ""):
            _fail("install.upgrade.prepare_arm_idempotent", f"rc={again.returncode} out={again.stdout}")
            return

    # An ordinary release published after arming must not repoint "staged" and
    # orphan the prepared digest, or the halt strands on a pruned image.
    real_tick = _shell_function(UPDATE_SH, "tick")
    with tempfile.TemporaryDirectory(prefix="tick-guards-armed-") as tmp:
        home = os.path.join(tmp, "home")
        os.makedirs(os.path.join(home, ".mirage", "upgrade"), exist_ok=True)
        os.makedirs(os.path.join(home, ".mirage", "env"), exist_ok=True)
        prepared = os.path.join(home, ".mirage", "upgrade", "prepared.json")
        Path(prepared).write_text(
            json.dumps({"upgrade_name": "v-halt", "plan_height": 777, "image": "img@sha256:" + ("d" * 64)}),
            encoding="utf-8",
        )
        # Sources must not live in the work dir; fetch_verify copies into it.
        src = os.path.join(tmp, "src")
        work = os.path.join(tmp, "work")
        os.makedirs(src, exist_ok=True)
        os.makedirs(work, exist_ok=True)
        state = os.path.join(tmp, "state.json")
        Path(state).write_text(json.dumps({"last_release_id": 5, "last_network_generation": 3}), encoding="utf-8")
        release = os.path.join(src, "release.json")
        Path(release).write_text(
            json.dumps(
                {
                    "version": "v9.9.9",
                    "release_id": 6,
                    "activation": "ordinary",
                    "upgrade_name": "",
                    "rollback_safe": False,
                    "consensus_breaking": False,
                    "image": "ghcr.io/miragefoundation/mirage-node@sha256:" + ("e" * 64),
                }
            ),
            encoding="utf-8",
        )
        network = os.path.join(src, "network.json")
        Path(network).write_text(json.dumps({"min_release": "v0.0.1", "generation": 3}), encoding="utf-8")
        script = f"""set -euo pipefail
HOME={home!r}
tmp={work!r}
STATE_FILE={state!r}
MANIFEST_URL=release
NETWORK_URL=network
fetch_verify() {{
  if [[ "$1" == release ]]; then cp {release!r} "$2"; else cp {network!r} "$2"; fi
  printf sig > "$2.sig"
}}
json_field() {{ python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$1" "$2"; }}
docker() {{ echo "docker must not run while an upgrade is armed: $*" >&2; return 99; }}
{_shell_function(UPDATE_SH, "version_at_least")}
{_shell_function(UPDATE_SH, "canonical_hash")}
{_shell_function(UPGRADE_SH, "arm_governed_upgrade")}
{real_tick}
tick
"""
        r = _run(["bash", "-c", script])
        after = json.loads(Path(state).read_text(encoding="utf-8"))
        if r.returncode != 0 or "is armed for height 777" not in (r.stdout or ""):
            _fail("install.upgrade.tick_refuses_over_armed", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        if after.get("staged") or after.get("last_release_id") != 5:
            _fail("install.upgrade.tick_restaged_over_armed", after)
            return

    with tempfile.TemporaryDirectory(prefix="activate-") as tmp:
        home = os.path.join(tmp, "home")
        state_dir = os.path.join(tmp, "state")
        launch_log = os.path.join(tmp, "launch.log")
        launcher = os.path.join(tmp, "launch")
        os.makedirs(os.path.join(home, ".mirage", "upgrade"), exist_ok=True)
        os.makedirs(os.path.join(home, ".mirage", "node", "data"), exist_ok=True)
        os.makedirs(state_dir, exist_ok=True)
        Path(os.path.join(home, ".mirage", "upgrade", "prepared.json")).write_text(
            json.dumps(
                {
                    "upgrade_name": "v-test",
                    "plan_height": 50,
                    "image": "img@sha256:" + ("c" * 64),
                }
            ),
            encoding="utf-8",
        )
        Path(os.path.join(home, ".mirage", "node", "data", "priv_validator_state.json")).write_text(
            json.dumps({"height": "50", "round": 0, "step": 0}) + "\n",
            encoding="utf-8",
        )
        Path(launcher).write_text(f"#!/bin/sh\necho launched >> {launch_log}\n", encoding="utf-8")
        os.chmod(launcher, 0o755)
        digest = "img@sha256:" + ("c" * 64)
        base = f"""set -euo pipefail
HOME={home!r}
STATE_DIR={state_dir!r}
STATE_FILE={os.path.join(state_dir, "state.json")!r}
LAUNCH={launcher!r}
wait_for_rpc() {{ return 0; }}
install_hosttools_from_image() {{ :; }}
docker() {{
  if [[ "$*" == *"image inspect"* ]]; then
    printf '%s\\n' {digest!r}
    return 0
  fi
  echo "unexpected docker $*" >&2
  return 99
}}
curl() {{
  if [[ "$*" == *current_plan* ]]; then printf '%s\\n' '{{"plan":null}}'; return 0; fi
  printf '%s\\n' '{{"result":{{"sync_info":{{"latest_block_height":"80"}}}}}}'
}}
query_local_rest() {{ curl "$@"; }}
{activate}
activate_if_halted
"""
        r = _run(["bash", "-c", base])
        if r.returncode != 0 or os.path.exists(launch_log):
            _fail(
                "install.upgrade.activate_without_marker",
                f"rc={r.returncode} err={r.stderr} log={os.path.exists(launch_log)}",
            )
            return

        Path(os.path.join(home, ".mirage", "node", "data", "upgrade-info.json")).write_text(
            json.dumps({"name": "forged", "height": 50}),
            encoding="utf-8",
        )
        r = _run(["bash", "-c", base])
        if r.returncode != 0 or os.path.exists(launch_log):
            _fail("install.upgrade.activate_forged_marker", f"rc={r.returncode} err={r.stderr}")
            return

        Path(os.path.join(home, ".mirage", "node", "data", "upgrade-info.json")).write_text(
            json.dumps({"name": "v-test", "height": 50}),
            encoding="utf-8",
        )
        Path(os.path.join(home, ".mirage", "upgrade", "prepared.json")).write_text(
            json.dumps({"upgrade_name": "v-test", "plan_height": 0, "image": "img@sha256:" + ("c" * 64)}),
            encoding="utf-8",
        )
        # A jailed or unregistered node never signs the halt block. The marker is
        # the authoritative proof it reached the halt, so it must still activate
        # instead of being stranded on the pre-upgrade binary forever.
        Path(os.path.join(home, ".mirage", "node", "data", "priv_validator_state.json")).write_text(
            json.dumps({"height": "0", "round": 0, "step": 0}) + "\n",
            encoding="utf-8",
        )
        r = _run(["bash", "-c", base])
        if (
            r.returncode != 0
            or not os.path.isfile(launch_log)
            or "matched v-test to halt marker at height 50" not in (r.stdout or "")
            or "did not sign the halt block" not in (r.stdout or "")
        ):
            _fail("install.upgrade.activate_never_signed", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        Path(launch_log).unlink()
        Path(os.path.join(home, ".mirage", "upgrade", "prepared.json")).write_text(
            json.dumps({"upgrade_name": "v-test", "plan_height": 50, "image": "img@sha256:" + ("c" * 64)}),
            encoding="utf-8",
        )

        # Signing already past the halt means the marker is stale and the swap
        # happened; that must go quiet rather than fail every 30s forever.
        Path(os.path.join(home, ".mirage", "node", "data", "priv_validator_state.json")).write_text(
            json.dumps({"height": "51", "round": 0, "step": 0}) + "\n",
            encoding="utf-8",
        )
        r = _run(["bash", "-c", base])
        if r.returncode != 0 or os.path.exists(launch_log):
            _fail("install.upgrade.activate_stale_marker", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        if os.path.exists(os.path.join(home, ".mirage", "upgrade", "prepared.json")):
            _fail("install.upgrade.stale_prepared_cleared", "stale prepared.json survived a passed halt")
            return

        Path(os.path.join(home, ".mirage", "upgrade", "prepared.json")).write_text(
            json.dumps({"upgrade_name": "v-test", "plan_height": 50, "image": "img@sha256:" + ("c" * 64)}),
            encoding="utf-8",
        )
        Path(os.path.join(home, ".mirage", "node", "data", "priv_validator_state.json")).write_text(
            json.dumps({"height": "50", "round": 0, "step": 0}) + "\n",
            encoding="utf-8",
        )
        Path(os.path.join(state_dir, "activating")).write_text("stale\n", encoding="utf-8")
        r = _run(["bash", "-c", base])
        if r.returncode != 0 or not os.path.isfile(launch_log):
            _fail("install.upgrade.activate_retry_stale", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
        if os.path.isfile(os.path.join(state_dir, "activating")):
            _fail("install.upgrade.activating_cleared", "activating marker left behind after success")
            return
        # Cosmos leaves upgrade-info.json in place, so a surviving prepared.json
        # would make the activation timer re-match this halt every 30s forever.
        if os.path.exists(os.path.join(home, ".mirage", "upgrade", "prepared.json")):
            _fail("install.upgrade.prepared_cleared", "prepared.json survived a successful activation")
            return
        state = json.loads(Path(state_dir, "state.json").read_text(encoding="utf-8"))
        if state.get("active_rollback_safe") is not False or state.get("active_consensus_breaking") is not True:
            _fail("install.upgrade.rollback_flags", state)
            return
        launched = Path(launch_log).read_text(encoding="utf-8").splitlines()
        if launched != ["launched"]:
            _fail("install.upgrade.activate_count", launched)
            return
        Path(launcher).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        os.chmod(launcher, 0o755)
        Path(launch_log).unlink()
        Path(os.path.join(home, ".mirage", "upgrade", "prepared.json")).write_text(
            json.dumps({"upgrade_name": "v-test", "plan_height": 50, "image": "img@sha256:" + ("c" * 64)}),
            encoding="utf-8",
        )
        r = _run(["bash", "-c", base])
        if r.returncode == 0 or os.path.isfile(os.path.join(state_dir, "activating")):
            _fail(
                "install.upgrade.activate_failure_clears",
                f"rc={r.returncode} activating={os.path.isfile(os.path.join(state_dir, 'activating'))} err={r.stderr}",
            )
            return

    recover = Path(os.path.join(REPO_ROOT, "scripts", "recover.sh")).read_text(encoding="utf-8")
    if "tmux send-keys" in recover or "pause_app_services" not in recover:
        _fail("install.upgrade.recover_tmux", "recover.sh still uses tmux or lost app-service pause")
        return
    rehearsal = Path(os.path.join(REPO_ROOT, "scripts", "test_upgrade.sh")).read_text(encoding="utf-8")
    if "tmux" in rehearsal:
        _fail("install.upgrade.rehearsal_tmux", "test_upgrade.sh still references tmux")
        return
    _pass("install.upgrade.prepare_and_activate")


def _write_zst_archive(dest: str, members: dict[str, bytes]) -> None:
    raw = dest + ".tar"
    with tarfile.open(raw, "w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    r = _run(["zstd", "-q", "-f", raw, "-o", dest])
    os.unlink(raw)
    if r.returncode != 0:
        raise RuntimeError(r.stderr or "zstd failed")
    os.chmod(dest, 0o600)


def _test_backup_restore_contracts() -> None:
    """Backup archives exclude signer state; restore refuses traversal, truncation, and shared locks."""
    backup_py = Path(os.path.join(REPO_ROOT, "deploy", "online_backup.py")).read_text(encoding="utf-8")
    restore_host = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-restore")).read_text(encoding="utf-8")
    restore_py = Path(os.path.join(REPO_ROOT, "deploy", "online_restore.py")).read_text(encoding="utf-8")
    if restore_host.find("online_backup.py") < 0 or restore_host.find("online_backup.py") > restore_host.find(
        "online_restore.py --yes"
    ):
        _fail("install.backup.prerestore", "mirage-restore must snapshot before mutating")
        return
    if 'svctl("stop", "indexer", "backend")' not in restore_py:
        _fail("install.backup.stop_scope", "restore must stop only indexer and backend")
        return
    if "application.db" not in restore_py or "priv_validator_state.json" not in backup_py:
        _fail("install.backup.excludes", "backup/restore must name chain DBs and signer state")
        return

    sys.path.insert(0, REPO_ROOT)
    from deploy import online_backup, online_restore

    with tempfile.TemporaryDirectory(prefix="backup-lock-") as tmp:
        lock = Path(tmp, "backup.lock")
        online_backup.LOCK_PATH = lock
        online_restore.LOCK_PATH = lock
        fd = online_backup.acquire_lock()
        try:
            try:
                online_restore.acquire_lock()
                _fail("install.backup.lock", "restore acquired the backup lock concurrently")
                return
            except online_restore.RestoreError as e:
                if "already running" not in str(e):
                    _fail("install.backup.lock_message", str(e))
                    return
        finally:
            os.close(fd)

    with tempfile.TemporaryDirectory(prefix="backup-extract-") as tmp:
        archive = os.path.join(tmp, "bad.tar.zst")
        _write_zst_archive(archive, {"../etc/passwd": b"nope"})
        dest = Path(tmp, "out")
        dest.mkdir()
        try:
            online_restore.extract_archive(Path(archive), dest)
            _fail("install.backup.traversal", "path traversal was accepted")
            return
        except online_restore.RestoreError as e:
            if "path traversal" not in str(e):
                _fail("install.backup.traversal_message", str(e))
                return

        _write_zst_archive(archive, {"node/data/priv_validator_state.json": b"{}"})
        dest2 = Path(tmp, "out2")
        dest2.mkdir()
        try:
            online_restore.extract_archive(Path(archive), dest2)
            _fail("install.backup.signer_in_archive", "signer state in an archive was accepted")
            return
        except online_restore.RestoreError as e:
            if "forbidden" not in str(e):
                _fail("install.backup.signer_message", str(e))
                return

        os.chmod(archive, 0o644)
        dest3 = Path(tmp, "out3")
        dest3.mkdir()
        try:
            online_restore.extract_archive(Path(archive), dest3)
            _fail("install.backup.mode", "mode 0644 archive was accepted")
            return
        except online_restore.RestoreError as e:
            if "0600" not in str(e):
                _fail("install.backup.mode_message", str(e))
                return

        manifest = {
            "schema": "mirage-backup-v1",
            "release_id": "1",
            "image": "img@sha256:" + ("a" * 64),
            "contents": [
                {"path": "dumps/indexer.dump", "sha256": "0" * 64, "bytes": 4},
                {"path": "dumps/backend.dump", "sha256": "0" * 64, "bytes": 4},
            ],
        }
        root = Path(tmp, "root")
        (root / "dumps").mkdir(parents=True)
        (root / "dumps" / "indexer.dump").write_bytes(b"data")
        (root / "dumps" / "backend.dump").write_bytes(b"data")
        (root / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        try:
            online_restore.verify_extracted(root)
            _fail("install.backup.hash", "hash mismatch was accepted")
            return
        except online_restore.RestoreError as e:
            if "hash mismatch" not in str(e):
                _fail("install.backup.hash_message", str(e))
                return

    host_backup = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-backup")).read_text(encoding="utf-8")
    if "--output and --stdout cannot be combined" not in host_backup:
        _fail("install.backup.mutex", "mirage-backup must reject --output with --stdout")
        return
    if "os.replace" not in host_backup or "${host_out}.sha256" not in host_backup:
        _fail("install.backup.host_atomic", "host --output must atomically publish archive and sha256")
        return
    _pass("install.backup.restore_safety")


def _test_card_amounts_fit() -> None:
    """MIRAGE amounts are abbreviated so a card never cuts one mid-word."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import status_dashboard as dash

    for amount, expected in (
        (999_999, "999,999"),
        (1_000_000, "1mm"),
        (1_500_000, "1.5mm"),
        (5_000_000, "5mm"),
        (123_400_000, "123mm"),
        (1_500_000_000, "1.5bn"),
    ):
        got = dash.format_mirage(amount)
        if got != expected:
            _fail("install.status.amount_format", f"{amount} rendered as {got!r}, expected {expected!r}")
            return

    # Grouped digits pushed the Validator card past its edge as "(floo..".
    validator = dash.ServiceStatus(
        "Validator",
        dash.Status.OK,
        "Active",
        {
            "moniker": "Amsterdam-Node",
            "tokens": 5_000_000,
            "power_pct": 0.025,
            "balance_mirage": 9_999_803.17,
            "min_liquid_mirage": 1_000_000.0,
            "registered": True,
            "active": True,
        },
    )
    retention = dash.ServiceStatus(
        "Retention",
        dash.Status.WARN,
        "Below expected",
        {
            "retained_blocks": 10_929,
            "expected_blocks": 201_600,
            "pruning_strategy": "custom",
            "pruning_keep_recent": 1000,
        },
    )
    for status in (validator, retention):
        card = dash.draw_card(status.name, status.status, dash.format_card_content(status))
        plain = [re.sub(r"\x1b\[[0-9;]*m", "", row) for row in card]
        clipped = [row for row in plain if ".." in row]
        if clipped:
            _fail("install.status.card_truncation", f"{status.name} card still cuts content: {clipped}")
            return
        if any("floor" in row for row in plain):
            _fail("install.status.card_floor", f"{status.name} card should not spell out the floor: {plain}")
            return
    _pass("install.status.card_amounts_fit")


def _test_cards_are_all_one_height() -> None:
    """Every card is the same height, however much a single card has to say.

    ~/.mirage grew a fifth subdirectory and Disk Usage silently rendered a row
    taller than the other nine, so its whole row of the grid did too. The height
    is a property of the layout, not of whichever card currently has the least to
    report, so a card with more data than fits shows the most useful of it rather
    than stretching.
    """
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import status_dashboard as dash

    # More subdirectories than a card can hold, deliberately not size-ordered.
    disk = dash.ServiceStatus(
        "Disk Usage",
        dash.Status.OK,
        "Total: 289.2 MB",
        {
            "total": 303_252_930,
            "breakdown": {
                "logs": 12_700_000,
                "node": 192_200_000,
                "well-known": 86_500,
                "postgres": 78_300_000,
                "asn": 5_900_000,
                "env": 4_096,
                "keyring": 2_048,
            },
        },
    )
    minimal = dash.ServiceStatus("Rewards", dash.Status.OK, "Quests OFF", {"payouts_enabled": False})
    heights = {}
    for status in (disk, minimal):
        content = dash.format_card_content(status)
        if len(content) != dash.CARD_CONTENT_LINES:
            _fail(
                "install.status.card_height",
                f"{status.name} rendered {len(content)} content lines, expected {dash.CARD_CONTENT_LINES}",
            )
            return
        heights[status.name] = len(dash.draw_card(status.name, status.status, content))
    if len(set(heights.values())) != 1:
        _fail("install.status.card_height", f"cards drew different heights: {heights}")
        return

    # The rows kept are the biggest consumers, which is the point of the card.
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", row) for row in dash.format_card_content(disk)]
    shown = [row for row in plain if row.strip()]
    for required in ("node", "postgres", "logs", "asn"):
        if not any(required in row for row in shown):
            _fail("install.status.card_height", f"Disk Usage dropped {required!r}, keeping {shown}")
            return
    for omitted in ("well-known", "keyring"):
        if any(omitted in row for row in shown):
            _fail("install.status.card_height", f"Disk Usage kept the smallest directory {omitted!r}: {shown}")
            return
    _pass("install.status.cards_are_all_one_height")


def _test_earnings_card() -> None:
    """Cumulative minted/fee counters produce honest 24h and 30d totals.

    Rows are (height, created_at, node_minted_total, node_fees_total). The card
    used to difference balance samples, which counted an inbound transfer as
    income and summed every up-tick rather than the net; on a relay account that
    churns constantly it reported earnings far above anything received.
    """
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import status_dashboard as dash

    now = 3_000_000
    # Cumulative totals carried in from long before the window opens: a window
    # must report what accrued inside it, never the lifetime total.
    minted0 = 900_000_000
    fees0 = 4_000_000
    rows = [
        (1, now - (25 * 60 * 60), minted0, fees0),
        (2, now - (23 * 60 * 60), minted0 + 1_000_000, fees0 + 100_000),
        (3, now - (12 * 60 * 60), minted0 + 30_000_000, fees0 + 400_000),
        (4, now - (1 * 60 * 60), minted0 + 34_400_000, fees0 + 600_000),
    ]
    details = dash.summarize_earnings_history(rows, now)
    expected = {
        "earned_24h": 33_400_000,
        "spent_24h": 500_000,
        "earned_30d": 34_400_000,
        "spent_30d": 600_000,
        "net_30d": 33_800_000,
        "sample_count": 4,
    }
    for key, value in expected.items():
        if details.get(key) != value:
            _fail("install.status.earnings_math", f"{key}={details.get(key)!r}, expected {value!r}")
            return

    # Spending more than was earned is a real state for a relay node, and the
    # 30d total has to be allowed to go negative rather than clamp to zero.
    loss = dash.summarize_earnings_history([(1, now - (20 * 60 * 60), 100, 100), (2, now - (60 * 60), 150, 900)], now)
    if loss["net_30d"] != -750:
        _fail("install.status.earnings_negative", f"net_30d={loss['net_30d']!r}, expected -750")
        return

    # A single sample cannot describe a window: with nothing to difference
    # against, the honest answer is zero, not the lifetime total.
    single = dash.summarize_earnings_history([(1, now - (60 * 60), 5_000_000, 1_000)], now)
    if single["earned_24h"] or single["spent_24h"] or single["net_30d"]:
        _fail("install.status.earnings_single_sample", f"one sample produced {single!r}")
        return

    for amount, expected_text in (
        (0, "0"),
        (1, "0.000001"),
        (12_345, "0.012345"),
        (1_234_567, "1.23"),
        (123_456_789, "123.5"),
        (1_234_000_000, "1,234"),
    ):
        got = dash.format_mirage_delta(amount)
        if got != expected_text:
            _fail("install.status.earnings_precision", f"{amount} rendered as {got!r}, expected {expected_text!r}")
            return

    earnings = dash.ServiceStatus("Earnings", dash.Status.OK, "Collecting · 23h", details)
    card = dash.draw_card(earnings.name, earnings.status, dash.format_card_content(earnings))
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", row) for row in card]
    rendered = "\n".join(plain)
    for label in ("Earned 24h:", "Spent 24h:", "Total 30d:"):
        if label not in rendered:
            _fail("install.status.earnings_content", f"missing {label!r}: {rendered}")
            return
    # Transfers in and out are not earnings, so no line may imply otherwise.
    for banned in ("Staked 24h:", "Earned 30d:"):
        if banned in rendered:
            _fail("install.status.earnings_content", f"card still shows {banned!r}: {rendered}")
            return
    if "Spent 24h:  -0.5 MIRAGE" not in rendered or "Total 30d:  +33.8 MIRAGE" not in rendered:
        _fail("install.status.earnings_lines", rendered)
        return
    if any(".." in row for row in plain):
        _fail("install.status.earnings_fit", f"earnings card cuts content: {plain}")
        return
    # "Spent" and "Total" are a letter shorter than "Earned", so without padding
    # their amounts sit one column to the left.
    columns = set()
    for row in plain:
        for marker in ("+", "-"):
            for amount in ("0.5 MIRAGE", "33.4 MIRAGE", "33.8 MIRAGE"):
                index = row.find(f"{marker}{amount}")
                if index >= 0:
                    columns.add(index)
    if len(columns) != 1:
        _fail("install.status.earnings_aligned", f"amounts start at columns {sorted(columns)}: {plain}")
        return
    compact = "\n".join(dash.render_compact_dashboard([earnings], 80, 24, 1))
    if "24h  +33.4 earned  -0.5 spent" not in compact or "30d  +33.8 total" not in compact:
        _fail("install.status.earnings_compact", compact)
        return
    _pass("install.status.earnings_card")


def _test_web_earnings_sources() -> None:
    """The web validator card reads the same counters as the terminal dashboard.

    It used to difference node_balance, so a node that had just been funded and
    had delegated reported its whole holding as 24h earnings and its delegation
    as burned. Both numbers were nonsense, and "burned" was the wrong word for
    coins that had merely moved.
    """
    backend = Path(os.path.join(REPO_ROOT, "web", "backend", "routes", "public.py")).read_text(encoding="utf-8")
    stats = backend[backend.index("def get_network_stats()") :]
    stats = stats[: stats.index("def _get_cached_supply_history")]
    # Comments explain the old behaviour by name, so judge the code alone.
    stats = "\n".join(line for line in stats.splitlines() if not line.strip().startswith("#"))
    if "node_minted_total" not in stats or "node_fees_total" not in stats:
        _fail("install.web_earnings.counters", "get_network_stats does not read the earnings counters")
        return
    if "node_balance" in stats:
        _fail("install.web_earnings.balance_diff", "get_network_stats still derives earnings from node_balance")
        return
    if '"spent_24h"' not in stats or "burned_24h" in stats:
        _fail("install.web_earnings.field", "get_network_stats must return spent_24h and not burned_24h")
        return
    # A failed read must surface, not be reported as zero earnings.
    earnings_block = stats[stats.index("node_minted_total, node_fees_total") : stats.index("resp = {")]
    if "except" in earnings_block:
        _fail("install.web_earnings.swallow", "get_network_stats silently reports zero earnings on error")
        return
    history = backend[backend.index("def _get_cached_supply_history") :]
    history = history[: history.index("def _get_last_seen_rollups")]
    for column in ("node_minted_total", "node_fees_total"):
        if column not in history:
            _fail("install.web_earnings.history", f"supply history does not expose {column}")
            return

    themes = os.path.join(REPO_ROOT, "web", "frontend", "src", "themes")
    for theme in sorted(os.listdir(themes)):
        view = os.path.join(themes, theme, "routes", "NetworkView.js")
        if not os.path.isfile(view):
            continue
        body = Path(view).read_text(encoding="utf-8")
        chart = body[body.index("function NodeMintBurnChart") :]
        end = chart.find("\nfunction ", 1)
        chart = chart[:end] if end > 0 else chart
        if "node_minted_total" not in chart or "node_balance" in chart:
            _fail(f"install.web_earnings.{theme}.chart", "earnings chart still charts balance movement")
            return
        if "Burned (24h)" in body or "burned_24h" in body:
            _fail(f"install.web_earnings.{theme}.label", "validator card still says Burned (24h)")
            return
        if "Spent (24h)" not in body or "spent_24h" not in body:
            _fail(f"install.web_earnings.{theme}.spent", "validator card does not show Spent (24h)")
            return

    hook = Path(os.path.join(REPO_ROOT, "web", "frontend", "src", "logic", "useNetwork.js")).read_text(encoding="utf-8")
    if "spent_24h" not in hook or "burned_24h" in hook:
        _fail("install.web_earnings.hook", "useNetwork does not map spent_24h")
        return
    _pass("install.web_earnings.sources")


def _test_node_earnings_attribution() -> None:
    """Only chain payouts and this node's own fees count; transfers never do."""
    from indexer.address_utils import module_address
    from indexer.main import CORE_MODULE_ADDRESS, Indexer
    from indexer.migrations.v1_38_5_add_node_earnings_counters import MIGRATION_KEY

    # The core module is the sender on every payout, so a wrong address here
    # would silently attribute nothing rather than fail.
    if CORE_MODULE_ADDRESS != "mirage1p4zltl2x9wx8p0lmzqpp4sdulul43u5m96x969":
        _fail("install.earnings.core_module_address", CORE_MODULE_ADDRESS)
        return
    if module_address("gov") != "mirage10d07y265gmmuvt4z0w9aw880jnsr700jvealeg":
        _fail("install.earnings.module_address_derivation", module_address("gov"))
        return

    node = "mirage1w77ptf0m759n9dnu4rflms8dm69a7g7vec6zu3"
    other = "mirage1rd00maj4htc0f550pjy302maywy2wtaxv8ntaq"

    def _ev(ev_type, attrs):
        return {"type": ev_type, "attributes": [{"key": k, "value": v} for k, v in attrs.items()]}

    result_obj = {
        "txs_results": [
            {
                "events": [
                    # This node paid to broadcast: real spending.
                    _ev("tx", {"fee": "141106000umirage", "fee_payer": node}),
                    # Another relayer's fee must not land on this node's card.
                    _ev("tx", {"fee": "999000000umirage", "fee_payer": other}),
                ]
            }
        ],
        "finalize_block_events": [
            # Mint payout from the core module: real income.
            _ev("transfer", {"sender": CORE_MODULE_ADDRESS, "recipient": node, "amount": "194349602umirage"}),
            # A user sending coins in is NOT income, and was the single biggest
            # source of the inflated figure the balance-diff card reported.
            _ev("transfer", {"sender": other, "recipient": node, "amount": "50000000000umirage"}),
            # A payout to a different validator is not this node's income.
            _ev("transfer", {"sender": CORE_MODULE_ADDRESS, "recipient": other, "amount": "1786556888umirage"}),
        ],
    }
    minted, fees = Indexer._node_earnings_delta(result_obj, node)
    if minted != 194_349_602 or fees != 141_106_000:
        _fail("install.earnings.attribution", f"minted={minted} fees={fees}")
        return

    # Multi-denom amounts must contribute only their umirage leg.
    mixed = {
        "finalize_block_events": [
            _ev("transfer", {"sender": CORE_MODULE_ADDRESS, "recipient": node, "amount": "7uother,25umirage"})
        ]
    }
    if Indexer._node_earnings_delta(mixed, node) != (25, 0):
        _fail("install.earnings.multi_denom", str(Indexer._node_earnings_delta(mixed, node)))
        return

    # A node with no resolved validator address must contribute nothing rather
    # than match empty-string attributes.
    if Indexer._node_earnings_delta(result_obj, "") != (0, 0):
        _fail("install.earnings.no_validator", str(Indexer._node_earnings_delta(result_obj, "")))
        return

    main_source = Path(os.path.join(REPO_ROOT, "indexer", "main.py")).read_text(encoding="utf-8")
    # The counters must commit inside the block transaction; writing them after
    # the checkpoint would double-count or drop a block on a crash.
    tx_body = main_source.split('with self.db.transaction(label="block"', 1)[-1].split("finally:", 1)[0]
    if "_accumulate_node_earnings" not in tx_body:
        _fail("install.earnings.not_atomic", "earnings counters are not folded in inside the block transaction")
        return
    if MIGRATION_KEY != "v1.38.5_add_node_earnings_counters":
        _fail("install.earnings.migration_key", MIGRATION_KEY)
        return

    database_source = Path(os.path.join(REPO_ROOT, "indexer", "database.py")).read_text(encoding="utf-8")
    for column in ("node_minted_total", "node_fees_total"):
        if f"ADD COLUMN IF NOT EXISTS {column} BIGINT" not in database_source:
            _fail("install.earnings.schema", f"supply_history does not persist {column}")
            return
    _pass("install.earnings.attribution")


def _test_staked_balance_history() -> None:
    """Staking and unbonding balances are sampled with liquid balance."""
    from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2 as staking_query_pb2
    from cosmpy.protos.cosmos.staking.v1beta1 import query_pb2_grpc as staking_query_pb2_grpc
    from indexer.chain_client import ChainClient
    from indexer.migrations.v1_37_0_add_node_staked_history import MIGRATION_KEY

    delegated = staking_query_pb2.QueryDelegatorDelegationsResponse()
    delegation = delegated.delegation_responses.add()
    delegation.balance.denom = "umirage"
    delegation.balance.amount = "5000000000000"
    unbonding = staking_query_pb2.QueryDelegatorUnbondingDelegationsResponse()
    unbonding_entry = unbonding.unbonding_responses.add().entries.add()
    unbonding_entry.balance = "250000000"

    stub = mock.Mock()
    stub.DelegatorDelegations.return_value = delegated
    stub.DelegatorUnbondingDelegations.return_value = unbonding
    channel = mock.MagicMock()
    with (
        mock.patch("indexer.chain_client.grpc.insecure_channel", return_value=channel),
        mock.patch.object(staking_query_pb2_grpc, "QueryStub", return_value=stub),
    ):
        got = ChainClient("http://127.0.0.1:26657").get_staked_balance("mirage1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqnrql8a")
    if got != 5_000_250_000_000:
        _fail("install.status.staked_query", f"delegated + unbonding returned {got}")
        return

    database_source = Path(os.path.join(REPO_ROOT, "indexer", "database.py")).read_text(encoding="utf-8")
    main_source = Path(os.path.join(REPO_ROOT, "indexer", "main.py")).read_text(encoding="utf-8")
    if "node_staked BIGINT" not in database_source or "node_staked = COALESCE" not in database_source:
        _fail("install.status.staked_schema", "supply_history does not persist node_staked")
        return
    if "get_staked_balance(self._validator_address)" not in main_source:
        _fail("install.status.staked_sampling", "indexer telemetry does not sample validator stake")
        return
    if MIGRATION_KEY != "v1.37.0_add_node_staked_history":
        _fail("install.status.staked_migration", MIGRATION_KEY)
        return
    _pass("install.status.staked_balance_history")


def _test_retention_building_up() -> None:
    """A window that has not filled yet is healthy; one that overruns is not."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import status_dashboard as dash

    window = 201_600
    cases = (
        # A freshly state-synced node starts at its snapshot base and grows.
        ((10_957, window, False, False), dash.Status.OK, "Building up"),
        ((10_957, window, True, False), dash.Status.OK, "Syncing"),
        ((window, window, False, False), dash.Status.OK, "Within range"),
        # Pruning is not reclaiming, so the disk keeps growing.
        ((window * 2, window, False, False), dash.Status.WARN, "Above expected"),
        ((window, window, False, True), dash.Status.WARN, "Config mismatch"),
    )
    for args, expected_status, expected_message in cases:
        status, message = dash.classify_retention(*args)
        if status != expected_status or message != expected_message:
            _fail(
                "install.status.retention",
                f"retained={args[0]} of {args[1]} (catching_up={args[2]}, mismatch={args[3]}) "
                f"gave {status.value}/{message!r}, expected {expected_status.value}/{expected_message!r}",
            )
            return
    _pass("install.status.retention_building_up")


def _test_catching_up_is_not_a_fault() -> None:
    """A node replaying history reads as syncing, a halted one still as broken.

    Both look identical in latest_block_time — hours old — and CometBFT reports
    catching_up=false through the whole replay, so a fresh install presented as
    four red cards with no hint that it was working exactly as intended.
    """
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import status_dashboard as dash

    behind = 9_960.0  # 2h 46m of chain history left to cover
    cases = (
        # (label, block_age, height_delta, age_delta, elapsed) -> status, message, has_eta
        ("tip", 3.0, 1, 0.0, 1.0, dash.Status.OK, "Running", False),
        ("replaying", behind, 6, 30.75, 1.5, dash.Status.WARN, "Catching up", True),
        # Advancing but not closing the gap: no honest ETA exists, still a sync.
        ("keeping pace", behind, 3, 0.0, 1.5, dash.Status.WARN, "Catching up", False),
        ("halted", behind, 0, 0.0, 1.5, dash.Status.ERROR, "No new blocks", False),
        ("unmeasured", behind, None, None, None, dash.Status.ERROR, "No new blocks", False),
        # Near the tip on a slow chain is not a catch-up.
        ("slow blocks", 30.0, 2, 1.0, 1.5, dash.Status.WARN, "Slow blocks", False),
    )
    for label, age, h_delta, age_delta, elapsed, want_status, want_message, want_eta in cases:
        progress = dash.BlockProgress(
            height=7_000_000,
            block_age_secs=age,
            height_delta=h_delta,
            age_delta_secs=age_delta,
            elapsed_secs=elapsed,
        )
        status, message, eta = dash.classify_block_progress(progress)
        if status != want_status or message != want_message or bool(eta) != want_eta:
            _fail(
                "install.status.catching_up",
                f"{label}: got {status.value}/{message!r}/eta={eta}, "
                f"expected {want_status.value}/{want_message!r}/eta={'set' if want_eta else 'none'}",
            )
            return

    # Two samples a second apart must diff without a live probe, which is what
    # makes the once-per-second dashboard free.
    with tempfile.TemporaryDirectory(prefix="progress-") as tmp:
        original = dash.PROGRESS_SAMPLE_PATH
        dash.PROGRESS_SAMPLE_PATH = os.path.join(tmp, "progress.json")
        try:
            dash._write_progress_sample(7_000_000, behind, time.time() - 1.0)
            second = dash.observe_block_progress(7_000_004, behind - 20, probe=False)
        finally:
            dash.PROGRESS_SAMPLE_PATH = original
    if second.height_delta != 4 or second.age_delta_secs != 20:
        _fail(
            "install.status.progress_sample",
            f"height_delta={second.height_delta} age_delta={second.age_delta_secs}, expected 4 and 20",
        )
        return
    sampled_message = dash.classify_block_progress(second)[1]
    if sampled_message != "Catching up":
        _fail("install.status.progress_verdict", f"sampled progress classified as {sampled_message!r}")
        return

    # The holding page answers 503 on every route on purpose while that happens,
    # so those failures are explained — but only while something is still behind.
    # A node parked at the tip with a dead backend must stay loud: that is how a
    # fresh install whose read-only DB grants never landed presents.
    def hold_case(behind_secs, indexer_lag, maintenance=True):
        statuses = [
            dash.ServiceStatus(
                "CometBFT",
                dash.Status.WARN if behind_secs else dash.Status.OK,
                "Catching up" if behind_secs else "Running",
                {"behind_secs": behind_secs} if behind_secs else {},
            ),
            dash.ServiceStatus("Backend", dash.Status.ERROR, "HTTP 503", {"maintenance": maintenance}),
            dash.ServiceStatus("Indexer", dash.Status.WARN, "Behind", {"lag": indexer_lag}),
            dash.ServiceStatus("Endpoints", dash.Status.ERROR, "Some unreachable", {"maintenance": maintenance}),
        ]
        dash.explain_sync_hold(statuses)
        return {s.name: s.status for s in statuses}

    hold_cases = (
        ("chain behind", hold_case(9_960, 0), dash.Status.WARN),
        ("indexer behind", hold_case(None, 8_000), dash.Status.WARN),
        ("at the tip, backend dead", hold_case(None, 0), dash.Status.ERROR),
        ("no holding page", hold_case(9_960, 0, maintenance=False), dash.Status.ERROR),
    )
    for label, got, want in hold_cases:
        if got["Backend"] != want or got["Endpoints"] != want:
            _fail(
                "install.status.sync_hold",
                f"{label}: backend={got['Backend'].value} endpoints={got['Endpoints'].value}, "
                f"expected both {want.value}",
            )
            return

    # Wiring: the same node state that produced "No new blocks" on a healthy
    # install must now reach the card as a catch-up.
    def fake_rpc(height: int, block_age_secs: float):
        block_time = datetime.now(timezone.utc) - timedelta(seconds=block_age_secs)

        def get(url, **_kwargs):
            if "/status" in url:
                body = {
                    "result": {
                        "sync_info": {
                            "latest_block_height": str(height),
                            "latest_block_time": block_time.isoformat().replace("+00:00", "Z"),
                            "catching_up": False,
                        },
                        "node_info": {"network": "mirage-1"},
                    }
                }
            elif "/net_info" in url:
                body = {"result": {"peers": [{}, {}, {}, {}]}}
            elif "/validators" in url:
                body = {"result": {"total": 4}}
            else:
                body = {}
            return mock.Mock(status_code=200, json=mock.Mock(return_value=body))

        return get

    with tempfile.TemporaryDirectory(prefix="checknode-") as tmp:
        original = dash.PROGRESS_SAMPLE_PATH
        dash.PROGRESS_SAMPLE_PATH = os.path.join(tmp, "progress.json")
        try:
            # Seeding the previous sample keeps the run off the live-probe path,
            # which is the same thing the once-per-second dashboard does.
            dash._write_progress_sample(7_000_000, behind + 30, time.time() - 1.0)
            with mock.patch.object(dash.requests, "get", fake_rpc(7_000_006, behind)):
                advancing = dash.check_node()
            dash._write_progress_sample(7_000_000, behind, time.time() - 1.0)
            with mock.patch.object(dash.requests, "get", fake_rpc(7_000_000, behind)):
                halted = dash.check_node()
        finally:
            dash.PROGRESS_SAMPLE_PATH = original

    if advancing.status != dash.Status.WARN or advancing.message != "Catching up":
        _fail(
            "install.status.check_node_catching_up",
            f"a stale block on an advancing node gave {advancing.status.value}/{advancing.message!r}",
        )
        return
    if not advancing.details.get("behind_secs") or not advancing.details.get("eta_secs"):
        _fail("install.status.check_node_catching_up", f"card is missing behind/eta: {advancing.details}")
        return
    if halted.status != dash.Status.ERROR or halted.message != "No new blocks":
        _fail(
            "install.status.check_node_halted",
            f"a stale block on a stopped chain gave {halted.status.value}/{halted.message!r}",
        )
        return

    # And the operator is told once, at the top, instead of reading it off four
    # separate degraded cards.
    banner = dash.format_sync_banner(
        [
            dash.ServiceStatus(
                name="CometBFT",
                status=dash.Status.WARN,
                message="Catching up",
                details={"behind_secs": int(behind), "eta_secs": 486},
            ),
            dash.ServiceStatus(
                name="Endpoints",
                status=dash.Status.WARN,
                message="Holding page (syncing)",
                details={"maintenance": True},
            ),
        ]
    )
    for required in ("CATCHING UP", "2h 46m behind", "~8m", "endpoints held"):
        if required not in (banner or ""):
            _fail("install.status.sync_banner", f"banner {banner!r} is missing {required!r}")
            return
    if dash.format_sync_banner([dash.ServiceStatus("CometBFT", dash.Status.OK, "Running", {})]) is not None:
        _fail("install.status.sync_banner", "a caught-up node must not show a catch-up banner")
        return
    _pass("install.status.catching_up_is_not_a_fault")


def _test_readonly_role_reads_new_indexer_tables() -> None:
    """A table the indexer creates after provisioning must be readable by the backend.

    ALTER DEFAULT PRIVILEGES applies only to tables created by the role it names,
    and it names whoever runs it unless told otherwise. Provisioning runs as
    postgres while the indexer builds its schema as mirage_indexer, so without
    FOR ROLE the read-only role gets SELECT on nothing a fresh install creates:
    the backend logs "permission denied for table chain_stats" forever, the
    maintenance gate never lifts, and the node serves the holding page for good.
    A string match on the grant cannot tell the two spellings apart, so this
    creates a table the way the indexer does and reads it the way the backend does.
    """
    name = "install.db.ro_reads_new_tables"
    try:
        import psycopg
    except Exception as e:
        _skip(name, f"psycopg unavailable: {e}")
        return

    rw_url = os.environ.get("INDEXER_DB_URL", "").strip()
    ro_url = os.environ.get("INDEXER_DB_RO_URL", "").strip()
    if not rw_url or not ro_url:
        _skip(name, "INDEXER_DB_URL/INDEXER_DB_RO_URL unavailable")
        return

    # public, not a throwaway schema: default privileges are granted per schema,
    # and public is the one the indexer and every migration actually use.
    table = f"grant_probe_{_rand_str(8)}"
    try:
        with psycopg.connect(rw_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE TABLE public."{table}" (id int)')
    except Exception as e:
        _skip(name, f"indexer DB not writable from here: {e}")
        return

    try:
        with psycopg.connect(ro_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'SELECT count(*) FROM public."{table}"')
                cur.fetchone()
                # And the tables the backend actually needs at startup.
                cur.execute("SELECT count(*) FROM chain_stats")
                cur.fetchone()
    except Exception as e:
        _fail(name, f"read-only role cannot read a newly created indexer table: {e}")
        return
    finally:
        with psycopg.connect(rw_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS public."{table}"')
    _pass(name)


def _test_param_load_fails_fast_on_denied_grant() -> None:
    """A missing grant stops the load; only a not-yet-populated table is waited on.

    The retry budget is an hour, for the indexer to write chain_params. A denied
    SELECT is not that race and never resolves, and spending the hour on it is
    how a broken install stayed quiet: 65 identical warnings, a maintenance page,
    and no statement of what was actually wrong.
    """
    name = "install.db.params_fail_fast"
    backend_src = os.path.join(REPO_ROOT, "web", "backend")
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)
    try:
        import psycopg

        import params as params_mod
    except Exception as e:
        _skip(name, f"backend modules not importable: {e}")
        return

    def denied():
        raise psycopg.errors.InsufficientPrivilege("permission denied for table chain_stats")

    started = time.monotonic()
    with mock.patch.object(params_mod, "_query_params_from_db", denied):
        try:
            params_mod.load_params(force=True, max_retries=5, retry_interval=30.0)
        except RuntimeError as e:
            message = str(e)
        except Exception as e:
            _fail(name, f"raised {type(e).__name__} instead of a RuntimeError explaining the grant: {e}")
            return
        else:
            _fail(name, "a denied SELECT on chain_stats was not treated as fatal")
            return
    elapsed = time.monotonic() - started

    if elapsed > 1.0:
        _fail(name, f"waited {elapsed:.1f}s before giving up; a denied grant must not be retried")
        return
    for required in ("read-only", "SELECT", "permission denied"):
        if required not in message:
            _fail(name, f"error message {message!r} does not mention {required!r}")
            return
    _pass(name)


def _maintenance_gate_run(
    tmp: str, stall_secs: int, backend_ready: bool, freeze_after: int
) -> subprocess.CompletedProcess:
    """Run the gate with curl/rm/sleep stubbed, so no wall-clock time passes."""
    fake = os.path.join(tmp, "bin")
    os.makedirs(fake, exist_ok=True)
    counter = os.path.join(tmp, "polls")
    removed = os.path.join(tmp, "removed")

    backend_rc = 0 if backend_ready else 22
    Path(os.path.join(fake, "curl")).write_text(
        f"""#!/bin/bash
case "$*" in
  *5000/api/get_node_config*) exit {backend_rc} ;;
  *26657/status*)
    n=$(cat {counter!r} 2>/dev/null || echo 0)
    n=$((n + 1))
    echo "$n" > {counter!r}
    if [ "$n" -gt {freeze_after} ]; then n={freeze_after}; fi
    echo "{{\\"result\\":{{\\"sync_info\\":{{\\"latest_block_height\\":\\"$((7000000 + n))\\"}}}}}}"
    ;;
  *) exit 22 ;;
esac
""",
        encoding="utf-8",
    )
    # The flag lives at an absolute path a test must not touch, and instant
    # sleeps keep a multi-hour sync inside a test run.
    Path(os.path.join(fake, "rm")).write_text(f'#!/bin/bash\necho "$*" >> {removed!r}\n', encoding="utf-8")
    Path(os.path.join(fake, "sleep")).write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    for name in ("curl", "rm", "sleep"):
        os.chmod(os.path.join(fake, name), 0o755)

    env = dict(os.environ)
    env["PATH"] = fake + os.pathsep + env["PATH"]
    env["CHAIN_STARTUP_GRACE_SECONDS"] = str(stall_secs)
    result = subprocess.run(
        ["bash", os.path.join(REPO_ROOT, "deploy", "run_maintenance_gate.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    result.removed_flag = os.path.isfile(removed)  # type: ignore[attr-defined]
    return result


def _test_maintenance_gate_tracks_progress() -> None:
    """A syncing node keeps the maintenance page; a stalled one still fails."""
    stall = 20

    # A node replaying blocks answers 503 for hours. The gate used to give up on
    # a wall clock and, with autorestart=false, left the page up forever.
    with tempfile.TemporaryDirectory(prefix="gate-syncing-") as tmp:
        r = _maintenance_gate_run(tmp, stall, backend_ready=False, freeze_after=200)
        if r.returncode == 0 or r.removed_flag:  # type: ignore[attr-defined]
            _fail("install.gate.syncing", f"gate lifted maintenance for an unready backend: rc={r.returncode}")
            return
        elapsed = [int(m) for m in re.findall(r"\((\d+)s elapsed", r.stdout)]
        if not elapsed or max(elapsed) <= stall:
            _fail(
                "install.gate.waits_while_syncing",
                f"gave up after {max(elapsed) if elapsed else 0}s despite block progress (stall limit {stall}s)",
            )
            return
        if "has not advanced" not in r.stderr:
            _fail("install.gate.stall_message", f"unclear failure: {r.stderr!r}")
            return

    # A node that is not advancing must still fail inside the stall window.
    with tempfile.TemporaryDirectory(prefix="gate-stalled-") as tmp:
        r = _maintenance_gate_run(tmp, stall, backend_ready=False, freeze_after=0)
        if r.returncode == 0 or r.removed_flag:  # type: ignore[attr-defined]
            _fail("install.gate.stalled", f"stalled node did not fail: rc={r.returncode}")
            return
        elapsed = [int(m) for m in re.findall(r"\((\d+)s elapsed", r.stdout)]
        if elapsed and max(elapsed) > stall + 60:
            _fail("install.gate.stall_bound", f"stalled node waited {max(elapsed)}s for a {stall}s limit")
            return

    # A ready backend lifts the page.
    with tempfile.TemporaryDirectory(prefix="gate-ready-") as tmp:
        r = _maintenance_gate_run(tmp, stall, backend_ready=True, freeze_after=0)
        if r.returncode != 0 or not r.removed_flag:  # type: ignore[attr-defined]
            _fail("install.gate.lifts", f"rc={r.returncode} out={r.stdout} err={r.stderr}")
            return
    _pass("install.gate.tracks_sync_progress")


def _test_status_compact_layout() -> None:
    """80x24 terminals use the compact renderer; live mode restores the alternate screen."""
    dashboard = Path(os.path.join(REPO_ROOT, "scripts", "status_dashboard.py")).read_text(encoding="utf-8")
    status_tool = Path(os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-status")).read_text(encoding="utf-8")
    if "\\033[?1049h" not in dashboard or "sys.exit(130)" not in dashboard:
        _fail("install.status.altscreen", "interactive dashboard must use the alternate screen and exit 130 on Ctrl+C")
        return
    if "SIGWINCH" not in dashboard:
        _fail("install.status.resize", "dashboard must refresh on SIGWINCH")
        return
    if "SIGTERM" not in dashboard or "SIGHUP" not in dashboard:
        _fail("install.status.restores_on_signal", "a killed dashboard must still leave the alternate screen")
        return
    if "docker exec -it" not in status_tool or "--once" not in status_tool:
        _fail("install.status.host_tty", "mirage-status must allocate a TTY only for live mode")
        return
    if "SESSION_LIMIT_SECS" in dashboard or "ended after" in dashboard:
        _fail("install.status.no_session_timeout", "live status still terminates a legitimate session on a timer")
        return
    for required in (
        "MIRAGE_STATUS_PID_FILE",
        "trap cleanup_status_session EXIT",
        "/proc/{pid}/cmdline",
        "os.kill(pid, signal.SIGTERM)",
    ):
        if required not in status_tool:
            _fail("install.status.disconnect_cleanup", f"host wrapper is missing {required!r}")
            return

    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import status_dashboard as dash

    pid_path = Path(f"/tmp/mirage-status-{os.getpid()}-{os.getppid()}-{threading.get_ident()}.pid")
    try:
        created = dash.create_session_pid_file(str(pid_path))
        if created != pid_path or pid_path.read_text(encoding="utf-8").strip() != str(os.getpid()):
            _fail("install.status.pid_registration", "dashboard did not publish its exact process id")
            return
    finally:
        pid_path.unlink(missing_ok=True)
    try:
        dash.create_session_pid_file("/root/mirage-status-1-2-3.pid")
    except RuntimeError:
        pass
    else:
        _fail("install.status.pid_path", "dashboard accepted a pid file outside /tmp")
        return

    fake = [
        dash.ServiceStatus(
            "CometBFT", dash.Status.OK, "height 12", {"height": 12, "peers": 3, "supervisor_state": "RUNNING"}
        ),
        dash.ServiceStatus("Backend", dash.Status.ERROR, "down", {"supervisor_state": "FATAL"}),
        dash.ServiceStatus("Indexer", dash.Status.WARN, "lag", {"lag": 4, "supervisor_state": "RUNNING"}),
    ]
    # The frame is built before anything is painted, so a slow collection can
    # no longer leave the terminal blank between refreshes.
    if "def paint(" not in dashboard or "\\033[?2026h" not in dashboard:
        _fail("install.status.in_place_repaint", "live dashboard must repaint in place with synchronized output")
        return
    if "\\033[2J\\033[H" in dashboard:
        _fail("install.status.no_clear_per_frame", "dashboard still erases the screen before collecting a frame")
        return

    # Read the renderers' source rather than capturing stdout: categories run in
    # parallel threads, and redirecting the process-wide stdout swallowed another
    # category's PASS line and blamed it on the renderer.
    for name in ("render_dashboard", "render_compact_dashboard"):
        if re.search(r"\b(print\(|sys\.stdout)", inspect.getsource(getattr(dash, name))):
            _fail("install.status.renderer_prints", f"{name} writes to stdout instead of returning a frame")
            return
    lines = dash.render_compact_dashboard(fake, 80, 24, 1)
    text = "\n".join(lines)
    if "Ctrl+C exits" not in text or "[FATAL]" not in text or "MIRAGE" not in text:
        _fail("install.status.compact_content", text)
        return
    visible_lines = [line for line in lines if line]
    if len(visible_lines) > 24:
        _fail("install.status.compact_height", f"{len(visible_lines)} lines for a 24-row terminal")
        return

    # The address an operator would type is the domain when there is one, and
    # the public IP otherwise. Both come from node.env, so no refresh-path lookup.
    ipv4 = {"DOMAIN": "", "EXTERNAL_ADDRESS": "tcp://203.0.113.7:26656"}
    cases = (
        (ipv4, "http://203.0.113.7"),
        ({"DOMAIN": "mirage.vote", "EXTERNAL_ADDRESS": "tcp://203.0.113.7:26656"}, "https://mirage.vote"),
        ({"DOMAIN": "", "EXTERNAL_ADDRESS": "tcp://[2001:db8::1]:26656"}, "http://[2001:db8::1]"),
    )
    for env, expected in cases:
        with mock.patch.dict(os.environ, env, clear=False):
            got = dash.node_public_url()
        if got != expected:
            _fail("install.status.address", f"{env} produced {got!r}, expected {expected!r}")
            return

    # The address and the key hints sit on the last two rows of the terminal.
    with mock.patch.dict(os.environ, ipv4, clear=False):
        pinned = dash.render_compact_dashboard(fake, 80, 24, 1, None, pin_bottom=True)
    if len(pinned) != 24:
        _fail("install.status.pinned_height", f"pinned frame is {len(pinned)} rows for a 24-row terminal")
        return
    if pinned[-2] != "http://203.0.113.7" or "Ctrl+C exits" not in pinned[-1]:
        _fail("install.status.pinned_trailer", f"bottom rows are {pinned[-2]!r} / {pinned[-1]!r}")
        return
    _pass("install.status.compact_80x24")
