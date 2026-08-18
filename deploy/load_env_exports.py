#!/usr/bin/env python3
"""Emit `export KEY=quoted` lines from dotenv files without executing values.

Env files are operator-editable and the installer writes human names into them.
Bash-sourcing those files ran `$()`, spaces, and semicolons as root. This
parser treats every value as a literal and quotes it for `eval`.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_env_file(path: Path) -> list[tuple[str, str]]:
    text = path.read_text(encoding="utf-8")
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SystemExit(f"{path}:{lineno}: not KEY=VALUE: {raw!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY.fullmatch(key):
            raise SystemExit(f"{path}:{lineno}: invalid env key {key!r}")
        if key in seen:
            raise SystemExit(f"{path}:{lineno}: duplicate key {key}")
        seen.add(key)
        if not value or value in ("''", '""'):
            value = ""
        elif value[:1] in "'\"":
            try:
                token = shlex.split(value)
            except ValueError as exc:
                raise SystemExit(f"{path}:{lineno}: quoted value is not parseable: {value!r} ({exc})") from exc
            if len(token) != 1:
                raise SystemExit(f"{path}:{lineno}: quoted value is not a single token: {value!r}")
            value = token[0]
        rows.append((key, value))
    return rows


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: load_env_exports.py FILE [FILE...]")
    for raw in sys.argv[1:]:
        path = Path(raw)
        if not path.is_file():
            raise SystemExit(f"{path}: env file does not exist")
        for key, value in parse_env_file(path):
            sys.stdout.write(f"export {key}={shlex.quote(value)}\n")


if __name__ == "__main__":
    main()
