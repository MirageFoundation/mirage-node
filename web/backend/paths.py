from __future__ import annotations

"""Paths helpers.

Functions:
- project_root(): Absolute project root path.
"""

import os


def project_root() -> str:
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.abspath(os.path.join(here, "../.."))


__all__ = ["project_root"]
