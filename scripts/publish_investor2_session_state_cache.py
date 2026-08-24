#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.publish_investor2_session_state_cache_impl import *  # noqa: E402,F403
from scripts.publish_investor2_session_state_cache_impl import main as _impl_main  # noqa: E402


def main() -> None:
    _impl_main()


if __name__ == "__main__":
    main()
