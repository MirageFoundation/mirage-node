#!/usr/bin/env python3
import os
import sys
import shlex
import subprocess
from dataclasses import dataclass


@dataclass
class Remote:
    user: str
    host: str
    port: int = 22

    @property
    def spec(self) -> str:
        return f"{self.user}@{self.host}"

    @property
    def key_name(self) -> str:
        return f"{self.user}@{self.host}"

    @property
    def ssh_config_host(self) -> str:
        return self.host


def abort(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def prompt_proceed(message: str) -> None:
    print(message)
    while True:
        ans = input("\nProceed? (y/n): ").strip().lower()
        if ans == "y":
            return
        if ans == "n":
            abort("User aborted.")
        print("Please enter 'y' or 'n'.")


def run(
    cmd: list[str], check: bool = True, timeout: int | None = None, capture_output: bool = False
) -> subprocess.CompletedProcess:
    printable = " ".join(shlex.quote(a) for a in cmd)
    print(f"$ {printable}")
    try:
        result = subprocess.run(
            cmd,
            check=False,
            text=True,
            capture_output=capture_output,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        abort(f"Command timed out: {printable}")
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        abort(f"Command failed ({result.returncode}): {printable}\n{stderr}")
    return result


def ensure_dir(path: str, mode: int = 0o700) -> None:
    os.makedirs(path, exist_ok=True)
    os.chmod(path, mode)


def write_file(path: str, content: str, mode: int | None = None) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if mode is not None:
        os.chmod(path, mode)


def update_ssh_config(remote: Remote, key_path: str) -> None:
    ssh_dir = os.path.expanduser("~/.ssh")
    ensure_dir(ssh_dir, 0o700)
    config_path = os.path.join(ssh_dir, "config")
    existing = ""
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            existing = f.read()

    # Remove any existing stanza for this host
    lines = existing.splitlines()
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().lower() == f"host {remote.ssh_config_host}".lower():
            # Skip until blank line or EOF
            i += 1
            while i < len(lines) and lines[i].strip() != "":
                i += 1
            # Also skip one trailing blank line if present
            if i < len(lines) and lines[i].strip() == "":
                i += 1
            continue
        out_lines.append(line)
        i += 1

    stanza = [
        "",
        f"Host {remote.ssh_config_host}",
        f"  HostName {remote.host}",
        f"  User {remote.user}",
        f"  Port {remote.port}",
        f"  IdentityFile {key_path}",
        "  PreferredAuthentications publickey",
        "  IdentitiesOnly yes",
        "  StrictHostKeyChecking accept-new",
        "  ServerAliveInterval 30",
        "  ServerAliveCountMax 3",
    ]
    new_config = "\n".join(out_lines + stanza) + ("\n" if not (out_lines and out_lines[-1] == "") else "")
    write_file(config_path, new_config, 0o600)
    print(f"✓ SSH config updated at {config_path} for host '{remote.ssh_config_host}'")


def generate_key_if_missing(key_path: str, comment: str) -> None:
    pub = f"{key_path}.pub"
    if os.path.exists(key_path) and os.path.exists(pub):
        print(f"✓ SSH key already exists: {key_path}")
        return
    prompt_proceed(f"\nAbout to generate SSH key '{key_path}' (RSA 4096, comment: {comment}).")
    run(["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", key_path, "-N", "", "-C", comment], check=True)
    print("✓ SSH key generated.")


def copy_public_key_to_remote(remote: Remote, pub_key_path: str) -> None:
    if not os.path.exists(pub_key_path):
        abort(f"Public key not found: {pub_key_path}")
    prompt_proceed(
        "\nAbout to copy your public key to the remote server using password authentication.\n"
        "You will likely be prompted for the remote password once."
    )
    cmd_str = (
        f"cat {shlex.quote(pub_key_path)} | "
        f"ssh -F /dev/null "
        "-o PreferredAuthentications=password -o PubkeyAuthentication=no "
        "-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "
        f"-p {remote.port} {shlex.quote(remote.spec)} "
        f"{shlex.quote('mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys')}"
    )
    cmd = ["sh", "-c", cmd_str]
    run(cmd, check=True)
    print("✓ Public key installed to remote ~/.ssh/authorized_keys")


def test_password_ssh(remote: Remote) -> bool:
    cmd = [
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "NumberOfPasswordPrompts=1",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(remote.port),
        remote.spec,
        "true",
    ]
    res = run(cmd, check=False)
    return res.returncode == 0


def ensure_password_ssh_works(remote: Remote) -> None:
    print("==> Testing initial SSH password login to the server (no keys).")
    prompt_proceed(
        "\nAbout to attempt SSH password login. You will be prompted for the remote password.\n"
        "This verifies basic access before any changes."
    )
    ok = test_password_ssh(remote)
    print(f"Result: {'OK' if ok else 'FAILED'}")
    if not ok:
        abort(
            "Password-based SSH failed. Cannot proceed to install a key.\n"
            "Ensure the server allows password login and that the credentials are correct."
        )
    print("✓ Password-based SSH connectivity confirmed.")


def test_ssh_direct(remote: Remote, key_path: str) -> bool:
    cmd = [
        "ssh",
        "-i",
        key_path,
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "PubkeyAuthentication=yes",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(remote.port),
        remote.spec,
        "exit",
    ]
    res = run(cmd, check=False)
    return res.returncode == 0


def test_ssh_config(remote: Remote) -> bool:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        "-p",
        str(remote.port),
        remote.ssh_config_host,
        "exit",
    ]
    res = run(cmd, check=False)
    return res.returncode == 0


def ensure_direct_ssh_works(remote: Remote, key_path: str) -> None:
    print("==> Verifying key-based SSH connectivity using explicit 'ssh -i key user@host'...")
    ok_direct = test_ssh_direct(remote, key_path)
    print(f"Result: {'OK' if ok_direct else 'FAILED'}")
    if not ok_direct:
        abort(
            "Key-based SSH test failed. Not proceeding. Please verify network access and authorized_keys on the remote."
        )
    print("✓ Key-based SSH works with explicit identity file.")


def ensure_config_ssh_works(remote: Remote) -> None:
    print("==> Verifying SSH connectivity using generic 'ssh <host>' (via ~/.ssh/config)...")
    ok = test_ssh_config(remote)
    print(f"Result: {'OK' if ok else 'FAILED'}")
    if not ok:
        abort("SSH via config host failed. Please inspect your ~/.ssh/config entry.")
    print("✓ SSH works via generic 'ssh <host>'.")


def remote_is_root(remote: Remote, key_path: str) -> bool:
    res = run(
        [
            "ssh",
            "-i",
            key_path,
            "-o",
            "BatchMode=yes",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "PubkeyAuthentication=yes",
            "-o",
            "ConnectTimeout=10",
            "-p",
            str(remote.port),
            remote.spec,
            "id",
            "-u",
        ],
        check=False,
        capture_output=True,
    )
    try:
        return res.returncode == 0 and (res.stdout or "").strip() == "0"
    except Exception:
        return False


def harden_remote_sshd(remote: Remote, key_path: str) -> None:
    is_root = remote_is_root(remote, key_path)
    sudo_prefix = "" if is_root else "sudo "
    prompt_proceed(
        "\nAbout to update remote SSH daemon configuration to enforce key-based auth only:\n"
        " - Backup /etc/ssh/sshd_config\n"
        " - Set PasswordAuthentication no\n"
        " - Ensure PubkeyAuthentication yes\n"
        " - Validate config (sshd -t)\n"
        " - Reload SSH daemon"
    )
    remote_script = r"""
set -euo pipefail
SSHD_CONFIG="/etc/ssh/sshd_config"
BACKUP_CONFIG="/etc/ssh/sshd_config.backup.$(date +%Y%m%d_%H%M%S)"
if [ ! -f "$SSHD_CONFIG" ]; then
  echo "Missing $SSHD_CONFIG" >&2
  exit 1
fi
{SUDO}cp "$SSHD_CONFIG" "$BACKUP_CONFIG"
echo "Backup created at: $BACKUP_CONFIG"

# Show current lines if present
grep -E '^(#\s*)?PasswordAuthentication|^(#\s*)?PubkeyAuthentication' "$SSHD_CONFIG" || true

# Disable PasswordAuthentication
if grep -qE '^PasswordAuthentication' "$SSHD_CONFIG"; then
  {SUDO}sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
else
  if grep -qE '^#PasswordAuthentication' "$SSHD_CONFIG"; then
    {SUDO}sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
  else
    echo "" | {SUDO}tee -a "$SSHD_CONFIG" >/dev/null
    echo "# Enforce key-based authentication" | {SUDO}tee -a "$SSHD_CONFIG" >/dev/null
    echo "PasswordAuthentication no" | {SUDO}tee -a "$SSHD_CONFIG" >/dev/null
  fi
fi

# Enable PubkeyAuthentication
if grep -qE '^PubkeyAuthentication' "$SSHD_CONFIG"; then
  {SUDO}sed -i 's/^PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD_CONFIG"
else
  if grep -qE '^#PubkeyAuthentication' "$SSHD_CONFIG"; then
    {SUDO}sed -i 's/^#PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSHD_CONFIG"
  else
    echo "" | {SUDO}tee -a "$SSHD_CONFIG" >/dev/null
    echo "# Enable public key authentication" | {SUDO}tee -a "$SSHD_CONFIG" >/dev/null
    echo "PubkeyAuthentication yes" | {SUDO}tee -a "$SSHD_CONFIG" >/dev/null
  fi
fi

echo "Validating sshd configuration..."
{SUDO}sshd -t -f "$SSHD_CONFIG"
echo "Validation OK"

echo "Reloading ssh daemon..."
if {SUDO}systemctl reload sshd 2>/dev/null || {SUDO}systemctl reload ssh 2>/dev/null; then
  echo "sshd reloaded via systemctl"
elif {SUDO}service sshd reload >/dev/null 2>&1 || {SUDO}service ssh reload >/dev/null 2>&1; then
  echo "sshd reloaded via service"
else
  echo "Could not reload sshd automatically; you may need to restart it manually." >&2
fi

echo "Current effective lines:"
grep -E '^PasswordAuthentication|^PubkeyAuthentication' "$SSHD_CONFIG" || true
""".replace(
        "{SUDO}", sudo_prefix
    )

    cmd = [
        "ssh",
        "-i",
        key_path,
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "PubkeyAuthentication=yes",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(remote.port),
        remote.spec,
        "bash",
        "-s",
    ]
    # Pipe the script to ssh stdin
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
    assert proc.stdin is not None
    proc.stdin.write(remote_script)
    proc.stdin.close()
    ret = proc.wait()
    if ret != 0:
        abort(f"Remote hardening script failed with exit code {ret}")
    print("✓ Remote SSH daemon configuration updated.")


def parse_remote(arg: str) -> Remote:
    if "@" not in arg:
        abort("Remote must be in the form user@host")
    user, host = arg.split("@", 1)
    host_part = host
    port = 22
    if ":" in host and host.count(":") == 1 and all(p.isdigit() for p in host.split(":")[1]):
        host_part, port_str = host.split(":")
        port = int(port_str)
    return Remote(user=user.strip(), host=host_part.strip(), port=port)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: scripts/setup_ssh.py user@host[:port]", file=sys.stderr)
        sys.exit(1)

    remote = parse_remote(sys.argv[1])
    ssh_dir = os.path.expanduser("~/.ssh")
    ensure_dir(ssh_dir, 0o700)

    key_path = os.path.join(ssh_dir, remote.key_name)
    pub_key_path = f"{key_path}.pub"
    comment = f"mirage-deploy-{remote.spec}"

    print(f"==> Remote: {remote.spec}")
    print(f"==> SSH key path: {key_path}")
    print(f"==> SSH config host entry: {remote.ssh_config_host}")
    print("")

    # Step 0: Ensure password-based SSH works before doing anything else
    ensure_password_ssh_works(remote)

    # Step 1: Generate key if missing
    generate_key_if_missing(key_path, comment)

    # Step 2: Copy public key to remote (password auth)
    copy_public_key_to_remote(remote, pub_key_path)

    # Step 3: Verify key-based SSH works (direct, without local config)
    prompt_proceed("\nAbout to verify key-based SSH connectivity before disabling password authentication.")
    ensure_direct_ssh_works(remote, key_path)

    # Step 4: Harden remote sshd (disable password auth)
    harden_remote_sshd(remote, key_path)

    # Step 5: Verify again after hardening (direct)
    print("==> Re-verifying SSH connectivity after hardening...")
    ensure_direct_ssh_works(remote, key_path)

    # Step 6: Update SSH config (at the very end) and verify 'ssh <host>'
    prompt_proceed(
        f"\nAbout to add/update SSH config entry for host '{remote.ssh_config_host}' using key '{key_path}'."
    )
    update_ssh_config(remote, key_path)
    ensure_config_ssh_works(remote)

    print("")
    print("✓ All done. You can now connect with:")
    print(f"  ssh {remote.ssh_config_host}")
    print(f"  ssh {remote.spec}")


if __name__ == "__main__":
    main()
