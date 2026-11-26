"""Whether records still differ on a uniqueness key is asked again only when a
change can have made them not (the keys themselves), and answers as before."""

from __future__ import annotations

from civex.repositories.local.record_repo import LocalRecordRepository

from .test_bulk_push import Batch, send


def _setup(project):
    b = Batch(project)
    laptop = b.laptop
    laptop.schema_svc.create("sample")
    laptop.schema_svc.add_field("sample", "tag", "string")
    laptop.commit()
    structure = b.take()
    for _ in range(2):
        laptop.record_svc.add("mine", "sample", {"tag": "x"})
        laptop.commit()
    records = [e for e in b.take() if e.entity_type == "record"]
    authority = project("authority")
    send(authority, b.structure + structure + records)
    return b, authority, records


def _spy(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = LocalRecordRepository.has_key_duplicate

    def spy(self, *a, **k):
        calls.append(1)
        return real(self, *a, **k)

    monkeypatch.setattr(LocalRecordRepository, "has_key_duplicate", spy)
    return calls


def test_a_new_key_over_records_that_share_it_is_refused(project, monkeypatch):
    b, authority, records = _setup(project)
    calls = _spy(monkeypatch)
    # (the laptop sees no duplicates: it only has the records the other made)
    b.laptop.record_svc.delete(str(records[1].entity_id))
    b.laptop.commit()
    b.take()
    b.laptop.schema_svc.set_unique_keys("sample", [["tag"]])
    b.laptop.commit()
    answers, _ = send(authority, b.take())
    assert [r[1] for r in answers] == ["rejected"]
    # (refused, not put back: the laptop keeps what it made)
    assert calls  # a change of the keys asks


def test_an_edit_that_leaves_the_keys_alone_does_not_read_the_records(
    project, monkeypatch
):
    b, authority, records = _setup(project)
    calls = _spy(monkeypatch)
    b.laptop.schema_svc.update("sample", description="about samples")
    b.laptop.commit()
    answers, _ = send(authority, b.take())
    assert [r[1] for r in answers] == ["applied"]
    assert not calls
