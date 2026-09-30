#!/usr/bin/env python3
"""Guards that keep `civex` and `civex-plugin-sdk` in step.

Run from the repo root. Stdlib + `packaging` only, so CI needs no install.
See docs/contributing/sdk-release.md for the model these enforce.

    check_sdk_sync.py check [--base REF]
        Always: the range civex declares for the SDK admits the in-repo SDK
        version, and the SDK's CHANGELOG has an entry for that version.
        With --base: if anything under civex-plugin-sdk/src changed since REF,
        the SDK version must have been raised.

    check_sdk_sync.py release-sdk TAG
        Before publishing the SDK: TAG is `sdk-v<version>` matching
        pyproject.toml, and that version is not already on PyPI.

    check_sdk_sync.py require-published
        Before publishing civex: the in-repo SDK version is already on PyPI,
        so the published civex wheel can actually resolve its dependency.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parent.parent
SDK_DIR = "civex-plugin-sdk"
SDK_NAME = "civex-plugin-sdk"


class GuardError(Exception):
    """A guard failed; the message says what to do about it."""


def sdk_version(text: str) -> Version:
    return Version(tomllib.loads(text)["project"]["version"])


def civex_sdk_requirement(text: str) -> Requirement:
    for dep in tomllib.loads(text)["project"]["dependencies"]:
        req = Requirement(dep)
        if req.name == SDK_NAME:
            return req
    raise GuardError(f"pyproject.toml has no {SDK_NAME} dependency.")


def check_range(civex_pyproject: str, sdk_pyproject: str) -> None:
    req = civex_sdk_requirement(civex_pyproject)
    version = sdk_version(sdk_pyproject)
    if not req.specifier.contains(version, prereleases=True):
        raise GuardError(
            f"civex depends on '{req}', which does not admit the in-repo SDK "
            f"version {version}. Update the range in pyproject.toml (or the "
            f"SDK version) so they agree."
        )


def check_changelog(
    sdk_changelog: str, version: Version, *, releasing: bool = False
) -> None:
    m = re.search(rf"^## v{re.escape(str(version))}([\s(].*)?$", sdk_changelog, re.M)
    if not m:
        raise GuardError(
            f"{SDK_DIR}/CHANGELOG.md has no '## v{version}' entry. Add one "
            f"describing what changed."
        )
    if releasing and "unreleased" in m.group(0).lower():
        raise GuardError(
            f"{SDK_DIR}/CHANGELOG.md still marks v{version} as unreleased. "
            f"Change the heading to '## v{version} (YYYY-MM-DD)' before tagging."
        )


def check_bumped(
    src_changed: bool, base_version: Version | None, head_version: Version
) -> None:
    if not src_changed or base_version is None:
        return
    if head_version <= base_version:
        raise GuardError(
            f"{SDK_DIR}/src changed but the SDK version is still {head_version} "
            f"(base: {base_version}). Raise `version` in {SDK_DIR}/pyproject.toml "
            f"-- the bump is what makes uv re-resolve cached plugin environments "
            f"-- and add a CHANGELOG entry."
        )


def check_release_tag(tag: str, version: Version, published: set[str]) -> None:
    if tag != f"sdk-v{version}":
        raise GuardError(
            f"Tag '{tag}' does not match {SDK_DIR}/pyproject.toml version "
            f"{version} (expected 'sdk-v{version}')."
        )
    if str(version) in published:
        raise GuardError(
            f"{SDK_NAME} {version} is already on PyPI; versions can't be "
            f"re-published. Bump the version and tag again."
        )


def check_published(version: Version, published: set[str]) -> None:
    if str(version) not in published:
        raise GuardError(
            f"{SDK_NAME} {version} is not on PyPI yet. Publish the SDK first "
            f"(push tag 'sdk-v{version}'), then release civex -- otherwise "
            f"`pip install civex` can't resolve its dependency."
        )


# -- I/O ----------------------------------------------------------------------


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def published_versions(timeout: float = 15.0) -> set[str]:
    """Versions of the SDK on PyPI (empty if the project doesn't exist yet)."""
    url = f"https://pypi.org/pypi/{SDK_NAME}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return set(json.load(resp)["releases"])
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise


def _cmd_check(base: str | None) -> None:
    head = _read(f"{SDK_DIR}/pyproject.toml")
    check_range(_read("pyproject.toml"), head)
    check_changelog(_read(f"{SDK_DIR}/CHANGELOG.md"), sdk_version(head))
    if base:
        changed = _git("diff", "--name-only", f"{base}...HEAD", "--", f"{SDK_DIR}/src")
        try:
            base_version: Version | None = sdk_version(
                _git("show", f"{base}:{SDK_DIR}/pyproject.toml")
            )
        except subprocess.CalledProcessError:
            base_version = None  # SDK didn't exist at base
        check_bumped(bool(changed.strip()), base_version, sdk_version(head))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--base", help="git ref to diff SDK changes against")
    p_rel = sub.add_parser("release-sdk")
    p_rel.add_argument("tag")
    sub.add_parser("require-published")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "check":
            _cmd_check(args.base)
        elif args.cmd == "release-sdk":
            version = sdk_version(_read(f"{SDK_DIR}/pyproject.toml"))
            check_release_tag(args.tag, version, published_versions())
            check_changelog(_read(f"{SDK_DIR}/CHANGELOG.md"), version, releasing=True)
        else:
            version = sdk_version(_read(f"{SDK_DIR}/pyproject.toml"))
            check_published(version, published_versions())
    except GuardError as e:
        print(f"::error::{e}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
