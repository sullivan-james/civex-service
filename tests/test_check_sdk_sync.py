"""Guards in scripts/check_sdk_sync.py that keep civex and civex-plugin-sdk in step."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from packaging.version import Version

_SPEC = importlib.util.spec_from_file_location(
    "check_sdk_sync", Path(__file__).resolve().parent.parent / "scripts/check_sdk_sync.py"
)
assert _SPEC and _SPEC.loader
guards = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guards)

V = Version


def _civex(dep: str) -> str:
    return f'[project]\ndependencies = ["typer", "{dep}"]\n'


def _sdk(version: str) -> str:
    return f'[project]\nname = "civex-plugin-sdk"\nversion = "{version}"\n'


def test_range_admits_in_repo_version() -> None:
    guards.check_range(_civex("civex-plugin-sdk>=0.2.0,<0.3"), _sdk("0.2.4"))


@pytest.mark.parametrize("version", ["0.3.0", "0.1.9"])
def test_range_rejects_version_outside_it(version: str) -> None:
    with pytest.raises(guards.GuardError, match="does not admit"):
        guards.check_range(_civex("civex-plugin-sdk>=0.2.0,<0.3"), _sdk(version))


def test_missing_dependency_is_an_error() -> None:
    with pytest.raises(guards.GuardError, match="no civex-plugin-sdk dependency"):
        guards.check_range('[project]\ndependencies = ["typer"]\n', _sdk("0.2.0"))


def test_the_real_repo_is_in_sync() -> None:
    root = Path(__file__).resolve().parent.parent
    head = (root / "civex-plugin-sdk/pyproject.toml").read_text()
    guards.check_range((root / "pyproject.toml").read_text(), head)
    guards.check_changelog(
        (root / "civex-plugin-sdk/CHANGELOG.md").read_text(), guards.sdk_version(head)
    )


def test_changelog_entry_required() -> None:
    log = "# Changelog\n\n## v0.2.0 (2026-09-30)\n- x\n"
    guards.check_changelog(log, V("0.2.0"))
    with pytest.raises(guards.GuardError, match="no '## v0.2.1' entry"):
        guards.check_changelog(log, V("0.2.1"))


def test_changelog_does_not_match_a_version_prefix() -> None:
    with pytest.raises(guards.GuardError):
        guards.check_changelog("## v0.2.10 (2026-09-30)\n", V("0.2.1"))


def test_release_rejects_unreleased_heading() -> None:
    log = "## v0.2.0 (unreleased)\n"
    guards.check_changelog(log, V("0.2.0"))  # fine outside a release
    with pytest.raises(guards.GuardError, match="unreleased"):
        guards.check_changelog(log, V("0.2.0"), releasing=True)


def test_src_change_requires_a_bump() -> None:
    with pytest.raises(guards.GuardError, match="still 0.2.0"):
        guards.check_bumped(True, V("0.2.0"), V("0.2.0"))
    with pytest.raises(guards.GuardError):
        guards.check_bumped(True, V("0.2.0"), V("0.1.0"))
    guards.check_bumped(True, V("0.2.0"), V("0.2.1"))


def test_no_src_change_needs_no_bump() -> None:
    guards.check_bumped(False, V("0.2.0"), V("0.2.0"))
    guards.check_bumped(True, None, V("0.2.0"))  # SDK is new at this ref


def test_release_tag_must_match_version_and_be_unpublished() -> None:
    guards.check_release_tag("sdk-v0.2.0", V("0.2.0"), {"0.1.0"})
    with pytest.raises(guards.GuardError, match="does not match"):
        guards.check_release_tag("v0.2.0", V("0.2.0"), set())
    with pytest.raises(guards.GuardError, match="already on PyPI"):
        guards.check_release_tag("sdk-v0.2.0", V("0.2.0"), {"0.2.0"})


def test_civex_release_requires_sdk_on_pypi() -> None:
    guards.check_published(V("0.2.0"), {"0.2.0"})
    with pytest.raises(guards.GuardError, match="Publish the SDK first"):
        guards.check_published(V("0.2.0"), set())
