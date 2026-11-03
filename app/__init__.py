"""Interpreter guard imported before anything that uses 3.10+ syntax.

`python -m uvicorn app.main:app` imports the app package first, and a module
using `X | None` raises `TypeError` before any of its own code runs. Checking
here turns that opaque failure into a sentence naming the required version.
"""

import sys

MINIMUM = (3, 10)
REQUIRED = "3.10"


def check() -> None:
    if sys.version_info < MINIMUM:
        found = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise RuntimeError(
            f"Python {REQUIRED} or newer is required, found {found}. "
            "The code uses 'X | None' annotations, which older interpreters "
            "reject at import time with a bare TypeError. "
            f"Try: python3.11 -m venv .venv"
        )


check()
