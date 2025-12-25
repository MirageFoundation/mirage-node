#!/usr/bin/env python3
import os
import re
import sys
from pathlib import Path

USAGE = "Usage: render_template.py <input_template> <output_file>"

pattern = re.compile(r"\$\{([A-Z0-9_]+)\}")

def render(text: str) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        return os.environ.get(key, "")
    return pattern.sub(repl, text)


def main() -> int:
    if len(sys.argv) != 3:
        print(USAGE, file=sys.stderr)
        return 1
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if not src.is_file():
        print(f"ERROR: template not found: {src}", file=sys.stderr)
        return 1
    content = src.read_text()
    out = render(content)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
