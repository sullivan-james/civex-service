#!/usr/bin/env python3
"""The one rule for a civex release tag (`v*`). Run from the repo root.

Stdlib + `packaging` only, so CI needs no install.

    check_release_tag.py TAG
        TAG is a valid `v<version>`, and CHANGELOG.md has an entry for it.
        A final release needs its own heading (`## v1.3.0 — <label> (date)`).
        A pre-release (`v1.3.0rc1`, `v1.3.0b2`, `v1.3.0.dev1`) may also use
        the heading of the release it leads to (`## v1.3.0`) or
        `## Unreleased`, so a candidate can be cut before that entry is
        finished and dated.

    check_release_tag.py TAG --wheel-dir dist
        Also: dist holds exactly one civex wheel, and its version is TAG's
        (setuptools-scm reads the version from git, so a wrong checkout or a
        missing tag would otherwise publish some other number).

Prints the version and whether it is a pre-release, and when GITHUB_OUTPUT is
set writes them there as `version` and `prerelease` (true/false) for later
jobs.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from packaging.utils import parse_wheel_filename
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
HEADING = re.compile(r"^## (\S+)(?:\s|$)", re.MULTILINE)
UNRELEASED = "unreleased"


class GuardError(Exception):
    """A guard failed; the message says what to do about it."""


def parse_tag(tag: str) -> Version:
    if not tag.startswith("v"):
        raise GuardError(f"Tag '{tag}' must look like 'vX.Y.Z' (or 'vX.Y.ZrcN').")
    try:
        version = Version(tag[1:])
    except InvalidVersion as exc:
        raise GuardError(f"Tag '{tag}' isn't a valid version: {exc}") from None
    if version.local:
        raise GuardError(f"Tag '{tag}' has a local part ('+...'); PyPI refuses it.")
    return version


def _heading_version(word: str) -> Version | None:
    if not word.startswith("v"):
        return None
    try:
        return Version(word[1:])
    except InvalidVersion:
        return None


def check_changelog(tag: str, version: Version, text: str) -> str:
    """The heading that covers this tag, or GuardError saying what to add."""
    words = HEADING.findall(text)
    for word in words:
        if _heading_version(word) == version:
            return f"## {word}"
    if version.is_prerelease:
        final = Version(version.base_version)
        for word in words:
            if _heading_version(word) == final or word.lower() == UNRELEASED:
                return f"## {word}"
        raise GuardError(
            f"No CHANGELOG.md entry covers {tag}. Add '## {tag}', "
            f"'## v{final}' or '## Unreleased' before pushing this tag."
        )
    raise GuardError(
        f"No CHANGELOG.md entry for {tag}. Add a '## {tag} — <label> (YYYY-MM-DD)' "
        "section before pushing this tag (see PRODUCTION_READINESS.md §4a)."
    )


def check_wheel(version: Version, wheel_dir: Path) -> Path:
    wheels = sorted(wheel_dir.glob("civex-*.whl"))
    if len(wheels) != 1:
        raise GuardError(
            f"Expected one civex wheel in {wheel_dir}, found {len(wheels)}."
        )
    built = parse_wheel_filename(wheels[0].name)[1]
    if built != version:
        raise GuardError(
            f"{wheels[0].name} is version {built}, but the tag says {version}. "
            "Check out with fetch-depth: 0 so setuptools-scm sees the tag."
        )
    return wheels[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag")
    parser.add_argument("--wheel-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        version = parse_tag(args.tag)
        heading = check_changelog(args.tag, version, CHANGELOG.read_text("utf-8"))
        wheel = check_wheel(version, args.wheel_dir) if args.wheel_dir else None
    except GuardError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    prerelease = "true" if version.is_prerelease else "false"
    print(f"version {version}, pre-release: {prerelease}, changelog: {heading}")
    if wheel:
        print(f"wheel {wheel.name} matches")
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"version={version}\nprerelease={prerelease}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
