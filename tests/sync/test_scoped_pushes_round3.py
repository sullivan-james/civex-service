"""Round-3 regressions: a deleted record under a parent is placed and checked
like any other, and the file-citation check asks every question every time."""

from __future__ import annotations

import uuid

from civex.testing import principal, statuses

from .test_scoped_pushes_review import _create, world  # noqa: F401

GONE = "2026-01-01T00:00:00+00:00"


def _deleted_under(authority, dataset, parent: str):
    entry = _create(authority, dataset, {"site": "c"})
    entry.new_data["parent_record_id"] = parent
    entry.new_data["deleted_at"] = GONE
    return entry


def test_a_deleted_child_under_a_hidden_or_absent_parent_is_refused_alike(world):
    authority, limited, open_, vault, seen, hidden, *_ = world
    who = principal(limited, "limited")
    answers = []
    for parent in (str(hidden.id), str(uuid.uuid4())):
        innocent = _create(authority, open_, {"site": "innocent"})
        result = limited.authority_svc.push(
            who, [innocent, _deleted_under(authority, open_, parent)]
        )
        assert statuses(result)[0] in ("applied", "rejected")
        assert statuses(result)[-1] == "rejected"
        d = result.results[-1].to_dict()
        answers.append((d["message"], d["conflicts"]))
        limited.commit()  # no integrity error, nothing rolled back
    assert answers[0] == answers[1]


def test_a_deleted_child_of_a_full_device_is_refused_or_placed_never_an_error(world):
    authority, _, open_, vault, seen, hidden, *_ = world
    full = principal(authority, "full")
    gone = authority.authority_svc.push(
        full, [_deleted_under(authority, open_, str(uuid.uuid4()))]
    )
    assert statuses(gone) == ["rejected"]
    authority.commit()
    placed = _deleted_under(authority, open_, str(hidden.id))
    result = authority.authority_svc.push(full, [placed])
    authority.commit()  # the placement matches its parent's, so commit holds
    assert statuses(result)[0] in ("applied", "merged")
    head = authority.authority_svc._applier.head("record", placed.entity_id)
    assert head["dataset_id"] == str(vault.id)


def test_every_citation_question_is_asked_for_every_hash(world):
    authority, limited, open_, vault, seen, hidden, secret, plain = world
    asked: list[str] = []
    real = limited.file_svc.exists
    limited.file_svc.exists = lambda sha: (asked.append(sha), real(sha))[1]
    from civex.domain.exceptions import ValidationError

    counts = []
    for sha in ("e" * 64, secret.sha256):
        asked.clear()
        try:
            limited.record_svc.add(
                "open",
                "encounter",
                {"site": "x", "scan": {"sha256": sha, "filename": "a", "size": 1}},
            )
        except ValidationError:
            pass
        counts.append(len(asked))
    assert counts[0] == counts[1] == 1
