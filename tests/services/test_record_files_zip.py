"""RecordService.files_for_zip -- the field-resolution/collision/guardrail
logic behind GET /records/{id}/files.zip."""
from __future__ import annotations

import civex.services.record_service as record_service
from civex.context import AppContext
from civex.domain.exceptions import NotFoundError, ValidationError

import pytest


def _ref(sha256: str, filename: str, size: int = 10) -> dict:
    return {"sha256": sha256, "filename": filename, "size": size}


def test_files_for_zip_gathers_file_and_file_list_fields(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "invoice",
        fields=[("scan", "file"), ("attachments", "file_list")],
    )
    make_collection("study")
    record = ctx.record_svc.add(
        "study",
        "invoice",
        {
            "scan": _ref("a" * 64, "scan.pdf"),
            "attachments": [_ref("b" * 64, "one.txt"), _ref("c" * 64, "two.txt")],
        },
    )
    ctx.commit()

    entries = ctx.record_svc.files_for_zip(str(record.id))
    names = {name for name, _ in entries}
    assert names == {"scan.pdf", "one.txt", "two.txt"}


def test_files_for_zip_scoped_to_single_field(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema(
        "invoice",
        fields=[("scan", "file"), ("attachments", "file_list")],
    )
    make_collection("study")
    record = ctx.record_svc.add(
        "study",
        "invoice",
        {
            "scan": _ref("a" * 64, "scan.pdf"),
            "attachments": [_ref("b" * 64, "one.txt")],
        },
    )
    ctx.commit()

    entries = ctx.record_svc.files_for_zip(str(record.id), field_name="attachments")
    assert [name for name, _ in entries] == ["one.txt"]


def test_files_for_zip_uses_resolved_filename(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("invoice", fields=[("invoice_number", "string"), ("scan", "file")])
    ctx.schema_svc.update_field(
        "invoice", "scan", restrictions={"filename_template": "{invoice_number}.{ext}"}
    )
    make_collection("study")
    record = ctx.record_svc.add(
        "study", "invoice", {"invoice_number": "INV-1", "scan": _ref("a" * 64, "upload.pdf")}
    )
    ctx.commit()

    entries = ctx.record_svc.files_for_zip(str(record.id))
    assert [name for name, _ in entries] == ["INV-1.pdf"]


def test_files_for_zip_appends_numeric_suffix_on_collision(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("invoice", fields=[("attachments", "file_list")])
    make_collection("study")
    record = ctx.record_svc.add(
        "study",
        "invoice",
        {
            "attachments": [
                _ref("a" * 64, "report.pdf"),
                _ref("b" * 64, "report.pdf"),
                _ref("c" * 64, "report.pdf"),
            ]
        },
    )
    ctx.commit()

    entries = ctx.record_svc.files_for_zip(str(record.id))
    names = [name for name, _ in entries]
    assert names == ["report.pdf", "report (1).pdf", "report (2).pdf"]
    assert len(set(names)) == 3


def test_files_for_zip_unknown_field_raises_not_found(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("invoice", fields=[("scan", "file")])
    make_collection("study")
    record = ctx.record_svc.add("study", "invoice", {"scan": _ref("a" * 64, "scan.pdf")})
    ctx.commit()

    with pytest.raises(NotFoundError):
        ctx.record_svc.files_for_zip(str(record.id), field_name="nope")


def test_files_for_zip_non_file_field_raises_validation_error(
    ctx: AppContext, make_schema, make_collection
) -> None:
    make_schema("invoice", fields=[("scan", "file"), ("subject", "string")])
    make_collection("study")
    record = ctx.record_svc.add(
        "study", "invoice", {"scan": _ref("a" * 64, "scan.pdf"), "subject": "S01"}
    )
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.record_svc.files_for_zip(str(record.id), field_name="subject")


def test_files_for_zip_unknown_record_raises_not_found(ctx: AppContext) -> None:
    with pytest.raises(NotFoundError):
        ctx.record_svc.files_for_zip("0" * 8)


def test_files_for_zip_enforces_count_guardrail(
    ctx: AppContext, make_schema, make_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record_service, "MAX_ZIP_FILE_COUNT", 2)
    make_schema("invoice", fields=[("attachments", "file_list")])
    make_collection("study")
    record = ctx.record_svc.add(
        "study",
        "invoice",
        {
            "attachments": [
                _ref("a" * 64, "one.txt"),
                _ref("b" * 64, "two.txt"),
                _ref("c" * 64, "three.txt"),
            ]
        },
    )
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.record_svc.files_for_zip(str(record.id))


def test_files_for_zip_enforces_total_size_guardrail(
    ctx: AppContext, make_schema, make_collection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record_service, "MAX_ZIP_TOTAL_SIZE", 15)
    make_schema("invoice", fields=[("attachments", "file_list")])
    make_collection("study")
    record = ctx.record_svc.add(
        "study",
        "invoice",
        {
            "attachments": [
                _ref("a" * 64, "one.txt", size=10),
                _ref("b" * 64, "two.txt", size=10),
            ]
        },
    )
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.record_svc.files_for_zip(str(record.id))
