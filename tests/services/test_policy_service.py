"""PolicyService: license text resolution + org-authored policy docs from
_civex/policies/*.md. New coverage -- no prior surface existed for this.
"""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError
from civex.services.policy_service import _find_license_text


def test_license_text_resolves_from_the_dev_source_tree() -> None:
    text = _find_license_text()
    assert "PolyForm Shield License" in text


def test_list_is_empty_when_no_policies_dir(ctx: AppContext) -> None:
    assert ctx.policy_svc.list() == []


def test_a_policy_can_be_written_listed_and_read_back(ctx: AppContext) -> None:
    policies_dir = ctx.policy_svc._dir
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "data-handling.md").write_text(
        "# Data Handling Policy\n\nDe-identify before export.\n"
    )

    listed = ctx.policy_svc.list()
    assert len(listed) == 1
    assert listed[0].stem == "data-handling"
    assert listed[0].title == "Data Handling Policy"

    fetched = ctx.policy_svc.get("data-handling")
    assert fetched.content == "# Data Handling Policy\n\nDe-identify before export.\n"


def test_title_falls_back_to_a_prettified_stem_without_a_heading(
    ctx: AppContext,
) -> None:
    policies_dir = ctx.policy_svc._dir
    policies_dir.mkdir(parents=True, exist_ok=True)
    (policies_dir / "retention_policy.md").write_text("No heading here.\n")

    fetched = ctx.policy_svc.get("retention_policy")
    assert fetched.title == "Retention Policy"


def test_get_unknown_stem_raises_not_found(ctx: AppContext) -> None:
    with pytest.raises(NotFoundError):
        ctx.policy_svc.get("nope")


def test_get_rejects_a_malformed_stem(ctx: AppContext) -> None:
    with pytest.raises(ValidationError, match="letters, numbers"):
        ctx.policy_svc.get("../../etc/passwd")
