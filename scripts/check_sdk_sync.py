#!/usr/bin/env python3
"""Guards that keep `civex` and `civex-plugin-sdk` in step.

Run from the repo root. Stdlib + `packaging` only, so CI needs no install.
See docs/contributing/sdk-release.md for the model these enforce.

The SDK has no version in its pyproject.toml: it comes from the newest
`sdk-v*` git tag (setuptools-scm). So "the in-repo SDK version" below always
means "the version of the newest `sdk-v*` tag reachable from HEAD".

    check_sdk_sync.py check [--base REF]
        The range civex declares for the SDK admits that version. With
        --base: if anything under civex-plugin-sdk/src changed since REF, the
        SDK's CHANGELOG.md must have changed too.

    check_sdk_sync.py release-sdk TAG
        Before publishing the SDK: TAG is a valid `sdk-v<version>`, that
        version is newer than everything on PyPI (and not already there), and
        CHANGELOG.md has a dated `## v<version>` entry.

    check_sdk_sync.py require-published
        Before publishing civex: the SDK version it depends on is on PyPI and
        the SDK's source hasn't changed since that tag, so the released SDK is
        exactly the one civex was built and tested against.
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
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
SDK_DIR = "civex-plugin-sdk"
SDK_NAME = "civex-plugin-sdk"
TAG_PREFIX = "sdk-v"
NO_TAG_HINT = (
    f"No '{TAG_PREFIX}*' tag is reachable from HEAD, so the SDK has no version. "
    "In CI, check out with fetch-depth: 0 so tags are fetched. Before the "
    f"first release, push the first tag (e.g. '{TAG_PREFIX}0.2.0')."
)


class GuardError(Exception):
    """A guard failed; the message says what to do about it."""


def parse_sdk_tag(tag: str) -> Version:
    if not tag.startswith(TAG_PREFIX):
        raise GuardError(f"Tag '{tag}' must look like '{TAG_PREFIX}X.Y.Z'.")
    try:
        return Version(tag[len(TAG_PREFIX) :])
    except InvalidVersion:
        raise GuardError(
            f"Tag '{tag}' does not end in a valid version (expected "
            f"'{TAG_PREFIX}X.Y.Z')."
        ) from None


def civex_sdk_requirement(pyproject: str) -> Requirement:
    for dep in tomllib.loads(pyproject)["project"]["dependencies"]:
        req = Requirement(dep)
        if req.name == SDK_NAME:
            return req
    raise GuardError(f"pyproject.toml has no {SDK_NAME} dependency.")


def check_range(civex_pyproject: str, version: Version | None) -> None:
    if version is None:
        raise GuardError(NO_TAG_HINT)
    req = civex_sdk_requirement(civex_pyproject)
    if not req.specifier.contains(version, prereleases=True):
        raise GuardError(
            f"civex depends on '{req}', which does not admit the newest SDK "
            f"tag ({TAG_PREFIX}{version}). Update the range in pyproject.toml "
            f"(or tag a version it admits) so they agree."
        )


def check_src_change_has_changelog(src_changed: bool, changelog_changed: bool) -> None:
    if src_changed and not changelog_changed:
        raise GuardError(
            f"{SDK_DIR}/src changed but {SDK_DIR}/CHANGELOG.md didn't. Describe "
            f"the change under the '## Unreleased' heading."
        )


def check_changelog_dated(sdk_changelog: str, version: Version) -> None:
    m = re.search(rf"^## v{re.escape(str(version))}([\s(].*)?$", sdk_changelog, re.M)
    if not m:
        raise GuardError(
            f"{SDK_DIR}/CHANGELOG.md has no '## v{version} (YYYY-MM-DD)' entry. "
            f"Rename '## Unreleased' to that before tagging."
        )
    if "unreleased" in m.group(0).lower():
        raise GuardError(
            f"{SDK_DIR}/CHANGELOG.md still marks v{version} as unreleased. "
            f"Change the heading to '## v{version} (YYYY-MM-DD)' before tagging."
        )


def check_release_tag(tag: str, published: set[str]) -> Version:
    version = parse_sdk_tag(tag)
    if str(version) in published:
        raise GuardError(
            f"{SDK_NAME} {version} is already on PyPI; versions can't be "
            f"re-published. Tag a new version."
        )
    newest = max((Version(v) for v in published), default=None)
    if newest is not None and version <= newest:
        raise GuardError(
            f"{tag} is not newer than the newest published version ({newest}). "
            f"Tag a higher version -- versions come from tags, so a typo here "
            f"would publish out of order."
        )
    return version


def check_ready_for_civex_release(
    version: Version | None, published: set[str], src_changed_since_tag: bool
) -> None:
    if version is None:
        raise GuardError(NO_TAG_HINT)
    if str(version) not in published:
        raise GuardError(
            f"{SDK_NAME} {version} is not on PyPI yet. Publish the SDK first "
            f"(push tag '{TAG_PREFIX}{version}'), then release civex -- "
            f"otherwise `pip install civex` can't resolve its dependency."
        )
    if src_changed_since_tag:
        raise GuardError(
            f"{SDK_DIR}/src has changed since {TAG_PREFIX}{version}, so the "
            f"published SDK isn't the one this civex was built against. Release "
            f"the SDK first (new '{TAG_PREFIX}*' tag), then civex."
        )


# -- I/O ----------------------------------------------------------------------


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def latest_sdk_version(ref: str = "HEAD") -> Version | None:
    """Version of the newest `sdk-v*` tag reachable from *ref*, if any."""
    try:
        tag = _git(
            "describe", "--tags", "--abbrev=0", "--match", f"{TAG_PREFIX}[0-9]*", ref
        ).strip()
    except subprocess.CalledProcessError:
        return None
    return parse_sdk_tag(tag)


def _changed(range_: list[str], path: str) -> bool:
    return bool(_git("diff", "--name-only", *range_, "--", path).strip())


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
            check_range(_read("pyproject.toml"), latest_sdk_version())
            if args.base:
                span = [f"{args.base}...HEAD"]
                check_src_change_has_changelog(
                    _changed(span, f"{SDK_DIR}/src"),
                    _changed(span, f"{SDK_DIR}/CHANGELOG.md"),
                )
        elif args.cmd == "release-sdk":
            version = check_release_tag(args.tag, published_versions())
            check_range(_read("pyproject.toml"), version)
            check_changelog_dated(_read(f"{SDK_DIR}/CHANGELOG.md"), version)
        else:
            version = latest_sdk_version()
            since = (
                _changed([f"{TAG_PREFIX}{version}", "HEAD"], f"{SDK_DIR}/src")
                if version is not None
                else False
            )
            check_ready_for_civex_release(version, published_versions(), since)
            check_range(_read("pyproject.toml"), version)
    except GuardError as e:
        print(f"::error::{e}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
