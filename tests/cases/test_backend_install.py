"""Source contracts for the one-command installer, signed manifests, and enrollment."""

from __future__ import annotations

import fcntl
import http.server
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path

from tests.common import _fail, _pass

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INSTALL_SH = os.path.join(REPO_ROOT, "deploy", "install.sh")
CREATE_VALIDATOR = os.path.join(REPO_ROOT, "deploy", "create_validator.sh")
RELEASE_VERIFY = os.path.join(REPO_ROOT, "deploy", "release_verify.py")
UPDATE_SH = os.path.join(REPO_ROOT, "deploy", "hosttools", "mirage-update")
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
    _test_setup_prompts()
    _test_prompt_answers_reach_env()
    _test_moniker_precedence()
    _test_frontend_env_no_foreign_node()
    _test_launch_wait()
    _test_activation_and_registration_waits()
    _test_pinned_bootstrap_dependencies()
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
    _test_hosttool_paths()
    _test_stake_floor_and_lock()
    _test_economics_single_source()
    _test_caddy_well_known()
    _test_repodigest_pin()


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
            _fail("install.agree_json.node_local", f"inbox counts still block the install: rc={r.returncode} {r.stderr}")
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


def _test_setup_prompts() -> None:
    """The install-time questions must answer themselves from the environment.

    Every prompt takes a variable so an unattended run never blocks, and a
    variable that is set but empty is a real answer: it is how an operator says
    "no domain" without being asked.
    """
    functions = _install_functions_only()
    script = (
        functions
        + '\nUSERNAME=alice\nPUBLIC_IP=203.0.113.7\n'
        + 'prompt_settings >/dev/null\n'
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
    if not re.search(r"if ! state_at_least configured; then\n\s+prompt_settings\n\s+configure\n", body):
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
            + f'write_env_key MEDIA_UPLOADS_ENABLED true {backend_env}\n'
        )
        r = _run(["bash", "-c", script])
        if r.returncode != 0:
            _fail("install.env_write.runs", f"rc={r.returncode} err={(r.stderr or '')[-200:]}")
            return
        node_text = Path(node_env).read_text(encoding="utf-8")
        backend_text = Path(backend_env).read_text(encoding="utf-8")
        if node_text != "MONIKER=chosen name\nWATCHDOG_AUTORECOVER=true\n":
            _fail("install.env_write.node_env", f"node.env is {node_text!r}")
            return
        if backend_text != "MEDIA_UPLOADS_ENABLED=true\n":
            _fail("install.env_write.backend_env", f"backend.env is {backend_text!r}")
            return
        for path in (node_env, backend_env):
            mode = os.stat(path).st_mode & 0o777
            if mode != 0o600:
                _fail("install.env_write.mode", f"{os.path.basename(path)} left at {oct(mode)}")
                return
    _pass("install.env_write.answers_reach_their_own_files")


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
        Path(launch_stub).write_text(f'#!/bin/bash\necho called >> {launched}\n', encoding="utf-8")
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
    _pass("install.launch.waits_for_first_boot_and_fails_fast_on_crash")


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
        referenced = {f"{package}/{module}.py" for package, module in re.findall(r"from (scripts|deploy)\.(\w+) import", workflow)}
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
    present = [name for name in forbidden if Path(REPO_ROOT, name).exists()]
    if present:
        _fail("install.image.secrets", f"sensitive build-context files present in runtime image: {present}")
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


def _test_updater_gates() -> None:
    """The updater must not re-stage what is running, replay an old manifest, or skip a release."""
    update = Path(REPO_ROOT, "deploy", "hosttools", "mirage-update").read_text(encoding="utf-8")
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    if "last_release_id" not in install or "/var/lib/mirage/update" not in install:
        _fail("install.updater.seed_state", "install.sh does not seed the updater state")
        return
    for needle, name in (
        ("generation < last_gen", "generation_rollback"),
        ("min_prior_version", "min_prior"),
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
        Path(launcher).write_text(f"#!/bin/sh\necho \"$*\" >> {launch_log}\n", encoding="utf-8")
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
            f'STATE_FILE="{state}"\nLAUNCH="{launcher}"\n'
            + _shell_function(UPDATE_SH, "rollback")
            + "rollback\n"
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
            "min_prior_version": "v1.36.1",
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
        functions = "".join(
            _shell_function(UPDATE_SH, name)
            for name in ("version_at_least", "canonical_hash", "tick")
        )
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
running_version() {{ echo {current_version}; }}
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
        installed = json.loads(
            Path(home, ".mirage", "env", "network-manifest.json").read_text(encoding="utf-8")
        )
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


def _test_repodigest_pin() -> None:
    install = Path(INSTALL_SH).read_text(encoding="utf-8")
    update = Path(REPO_ROOT, "deploy", "hosttools", "mirage-update").read_text(encoding="utf-8")
    if "RepoDigest" not in install or "RepoDigest" not in update:
        _fail("install.repodigest", "installer/updater must refuse a RepoDigest mismatch")
        return
    _pass("install.repodigest_pin")
