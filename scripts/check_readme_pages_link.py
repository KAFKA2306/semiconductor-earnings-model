#!/usr/bin/env python3
"""Enforce the shared rule that every delivered project README links its live GitHub Pages site."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def expected_pages_url(repository: str) -> str:
    owner, name = repository.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "KAFKA2306/semiconductor-earnings-model"))
    parser.add_argument("--readme", type=Path, default=Path(__file__).parents[1] / "README.md")
    args = parser.parse_args()
    content = args.readme.read_text(encoding="utf-8")
    expected = expected_pages_url(args.repository)
    if expected not in content:
        raise AssertionError(f"README must contain the live GitHub Pages URL: {expected}")
    flat = content.replace("\n", " ")
    if not re.search(r"(?i)(live|public|github pages|公開).{0,100}" + re.escape(expected), flat):
        raise AssertionError("GitHub Pages URL must be visibly labeled as the live/public site")
    print(f"readme_pages_link=PASS url={expected}")


if __name__ == "__main__":
    main()
