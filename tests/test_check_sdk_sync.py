"""Guards in scripts/check_sdk_sync.py that keep civex and civex-plugin-sdk in step."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from packaging.version import Version

_SPEC = importlib.util.spec_from_file_location(
    "check_sdk_sync",
    Path(__file__).resolve().parent.parent / "scripts/check_sdk_sync.py",
)
assert _SPEC and _SPEC.loader
guards = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guards)

V = Version


def _civex(dep: str) -> str:
    return f'[project]\ndependencies = ["typer", "{dep}"]\n'


RANGE = _civex("civex-plugin-sdk>=1.2.0,<1.3")


def test_range_admits_the_tagged_version_and_its_post_releases() -> None:
    guards.check_range(RANGE, V("1.2.4"))
    guards.check_range(RANGE, V("1.2.0.post3"))


@pytest.mark.parametrize("version", ["1.3.0", "1.1.9"])
def test_range_rejects_a_version_outside_it(version: str) -> None:
    with pytest.raises(guards.GuardError, match="does not admit"):
        guards.check_range(RANGE, V(version))


def test_no_tag_is_an_actionable_error() -> None:
    with pytest.raises(guards.GuardError, match="fetch-depth: 0"):
        guards.check_range(RANGE, None)


def test_missing_dependency_is_an_error() -> None:
    with pytest.raises(guards.GuardError, match="no civex-plugin-sdk dependency"):
        guards.check_range('[project]\ndependencies = ["typer"]\n', V("1.2.0"))


def test_the_real_repo_declares_a_range() -> None:
    root = Path(__file__).resolve().parent.parent
    req = guards.civex_sdk_requirement((root / "pyproject.toml").read_text())
    assert str(req.specifier)  # a range, not a bare unconstrained dependency


def test_the_sdk_pyproject_has_no_hard_coded_version() -> None:
    """The version comes from `sdk-v*` tags, never from the file."""
    import tomllib

    root = Path(__file__).resolve().parent.parent
    project = tomllib.loads((root / "civex-plugin-sdk/pyproject.toml").read_text())[
        "project"
    ]
    assert "version" not in project
    assert "version" in project["dynamic"]


def test_sdk_src_change_needs_a_changelog_change() -> None:
    with pytest.raises(guards.GuardError, match="CHANGELOG"):
        guards.check_src_change_has_changelog(True, False)
    guards.check_src_change_has_changelog(True, True)
    guards.check_src_change_has_changelog(False, False)


def test_release_changelog_must_have_a_dated_entry() -> None:
    log = "# Changelog\n\n## Unreleased\n- y\n\n## v0.2.0 (2026-09-30)\n- x\n"
    guards.check_changelog_dated(log, V("0.2.0"))
    with pytest.raises(guards.GuardError, match="no '## v0.2.1"):
        guards.check_changelog_dated(log, V("0.2.1"))


def test_release_changelog_does_not_match_a_version_prefix() -> None:
    with pytest.raises(guards.GuardError):
        guards.check_changelog_dated("## v0.2.10 (2026-09-30)\n", V("0.2.1"))


def test_release_rejects_an_undated_entry() -> None:
    with pytest.raises(guards.GuardError, match="unreleased"):
        guards.check_changelog_dated("## v0.2.0 (unreleased)\n", V("0.2.0"))


def test_release_tag_parsing() -> None:
    assert guards.check_release_tag("sdk-v0.2.0", set()) == V("0.2.0")
    for bad in ("v0.2.0", "sdk-v", "sdk-vbanana"):
        with pytest.raises(guards.GuardError):
            guards.check_release_tag(bad, set())


def test_release_tag_must_be_unpublished_and_newest() -> None:
    guards.check_release_tag("sdk-v0.3.0", {"0.1.0", "0.2.0"})
    with pytest.raises(guards.GuardError, match="already on PyPI"):
        guards.check_release_tag("sdk-v0.2.0", {"0.2.0"})
    with pytest.raises(guards.GuardError, match="not newer"):
        guards.check_release_tag("sdk-v0.0.1", {"0.2.0"})


def test_civex_release_requires_the_sdk_published() -> None:
    guards.check_ready_for_civex_release(V("0.2.0"), {"0.2.0"}, False)
    with pytest.raises(guards.GuardError, match="Publish the SDK first"):
        guards.check_ready_for_civex_release(V("0.2.0"), set(), False)
    with pytest.raises(guards.GuardError, match="fetch-depth"):
        guards.check_ready_for_civex_release(None, {"0.2.0"}, False)


def test_civex_release_refuses_unreleased_sdk_changes() -> None:
    with pytest.raises(guards.GuardError, match="has changed since"):
        guards.check_ready_for_civex_release(V("0.2.0"), {"0.2.0"}, True)
