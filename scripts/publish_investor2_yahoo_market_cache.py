#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.publish_investor2_yahoo_market_cache_impl import *  # noqa: F403
from scripts.publish_investor2_yahoo_market_cache_impl import main as _market_cache_main


def main() -> None:
    args = parse_args()  # noqa: F405
    _market_cache_main()

    payload = json.loads(args.config.read_text(encoding="utf-8"))
    followup = payload.get("session_state_cache_config")
    if followup is None:
        return
    if not isinstance(followup, str) or not followup.strip():
        raise ValueError("session_state_cache_config must be a non-empty relative path")
    followup_path = (args.config.parent / followup).resolve()
    config_root = args.config.parent.resolve()
    if config_root not in followup_path.parents:
        raise ValueError("session_state_cache_config must remain inside the config directory")
    script = Path(__file__).with_name("publish_investor2_session_state_cache.py")
    subprocess.run(
        [sys.executable, str(script), "--config", str(followup_path)],
        check=True,
    )


if __name__ == "__main__":
    main()
