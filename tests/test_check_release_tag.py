"""scripts/check_release_tag.py: what a `v*` tag needs before civex is released."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from packaging.version import Version

_SPEC = importlib.util.spec_from_file_location(
    "check_release_tag",
    Path(__file__).resolve().parent.parent / "scripts/check_release_tag.py",
)
assert _SPEC and _SPEC.loader
guards = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guards)

CHANGELOG = """# Changelog

## Unreleased — next things

## v1.2.1 — history (2026-10-05)

## v1.2.0 — uniqueness (2026-10-05)
"""
NO_UNRELEASED = CHANGELOG.replace("## Unreleased — next things\n\n", "")


def _check(tag: str, text: str = CHANGELOG) -> str:
    return guards.check_changelog(tag, guards.parse_tag(tag), text)


def test_a_final_release_needs_its_own_heading() -> None:
    assert _check("v1.2.1") == "## v1.2.1"
    with pytest.raises(guards.GuardError, match="No CHANGELOG.md entry for v1.3.0"):
        _check("v1.3.0")


def test_a_pre_release_may_use_unreleased_or_the_final_heading() -> None:
    assert _check("v1.3.0rc1") == "## Unreleased"
    text = NO_UNRELEASED.replace("# Changelog\n", "# Changelog\n\n## v1.3.0 — x\n")
    assert _check("v1.3.0rc1", text) == "## v1.3.0"
    assert _check("v1.3.0.dev2", text) == "## v1.3.0"


def test_a_pre_release_heading_of_its_own_wins_and_spellings_agree() -> None:
    text = CHANGELOG.replace("# Changelog\n", "# Changelog\n\n## v1.3.0rc1 — x\n")
    assert _check("v1.3.0-rc1", text) == "## v1.3.0rc1"


def test_a_pre_release_with_no_entry_at_all_is_refused() -> None:
    with pytest.raises(guards.GuardError, match="'## Unreleased'"):
        _check("v1.3.0rc1", NO_UNRELEASED)


@pytest.mark.parametrize("tag", ["1.3.0", "v1.x", "v1.3.0+local"])
def test_bad_tags_are_refused(tag: str) -> None:
    with pytest.raises(guards.GuardError):
        guards.parse_tag(tag)


def test_the_wheel_must_be_the_tag_s_version(tmp_path: Path) -> None:
    (tmp_path / "civex-1.3.0rc1-py3-none-any.whl").touch()
    assert guards.check_wheel(Version("1.3.0rc1"), tmp_path).name.startswith("civex")
    with pytest.raises(guards.GuardError, match="but the tag says 1.3.0"):
        guards.check_wheel(Version("1.3.0"), tmp_path)
    (tmp_path / "civex-1.2.0-py3-none-any.whl").touch()
    with pytest.raises(guards.GuardError, match="found 2"):
        guards.check_wheel(Version("1.3.0rc1"), tmp_path)


def test_main_writes_the_version_for_later_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG)
    monkeypatch.setattr(guards, "CHANGELOG", changelog)
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert guards.main(["v1.3.0rc1"]) == 0
    assert out.read_text() == "version=1.3.0rc1\nprerelease=true\n"
    assert guards.main(["v9.9.9"]) == 1
