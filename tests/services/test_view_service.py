"""ViewService: create/get/list/update/delete for saved column/filter/sort
definitions against a base schema's own fields."""

from __future__ import annotations

import pytest

from civex.context import AppContext
from civex.domain.exceptions import AlreadyExistsError, NotFoundError, ValidationError


def test_create_view_returns_defaults_for_omitted_fields(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string"), ("status", "string")])
    ctx.commit()

    view = ctx.view_svc.create("trial", "all_records")
    ctx.commit()

    assert view.name == "all_records"
    assert view.schema_name == "trial"
    assert view.columns == []
    assert view.filter_tree is None
    assert view.sort == []


def test_create_view_with_columns_filter_and_sort(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string"), ("status", "string")])
    ctx.commit()

    view = ctx.view_svc.create(
        "trial",
        "active",
        columns=["subject", "status"],
        filter_tree={"field": "status", "op": "eq", "value": "active"},
        sort=[{"field": "subject", "direction": "desc"}],
    )
    ctx.commit()

    assert view.columns == ["subject", "status"]
    assert view.filter_tree == {"field": "status", "op": "eq", "value": "active"}
    assert view.sort == [{"field": "subject", "direction": "desc"}]


def test_create_view_includes_inherited_fields(ctx: AppContext, make_schema):
    make_schema("base", fields=[("site", "string")])
    ctx.schema_svc.create("child", parent="base")
    ctx.schema_svc.add_field("child", "subject", "string")
    ctx.commit()

    view = ctx.view_svc.create("child", "with_inherited", columns=["subject", "site"])
    ctx.commit()

    assert view.columns == ["subject", "site"]


def test_create_view_rejects_unknown_column(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create("trial", "bad", columns=["nonexistent"])


def test_create_view_rejects_unknown_filter_field(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create(
            "trial", "bad", filter_tree={"field": "nonexistent", "op": "eq", "value": 1}
        )


def test_create_view_rejects_malformed_filter_tree(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create("trial", "bad", filter_tree={"op": "eq"})


def test_create_view_rejects_unknown_sort_field(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create("trial", "bad", sort=[{"field": "nonexistent"}])


def test_create_view_rejects_invalid_sort_direction(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create(
            "trial", "bad", sort=[{"field": "subject", "direction": "sideways"}]
        )


def test_create_view_rejects_non_slug_name(ctx: AppContext, make_schema):
    make_schema("trial")
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create("trial", "My View")


def test_create_view_on_missing_schema_raises_not_found(ctx: AppContext):
    with pytest.raises(NotFoundError):
        ctx.view_svc.create("missing", "view1")


def test_create_duplicate_view_name_on_same_schema_raises_already_exists(
    ctx: AppContext, make_schema
):
    make_schema("trial")
    ctx.commit()
    ctx.view_svc.create("trial", "view1")
    ctx.commit()

    with pytest.raises(AlreadyExistsError):
        ctx.view_svc.create("trial", "view1")


def test_same_view_name_allowed_on_different_schemas(ctx: AppContext, make_schema):
    make_schema("trial_a")
    make_schema("trial_b")
    ctx.commit()

    ctx.view_svc.create("trial_a", "active")
    ctx.view_svc.create("trial_b", "active")
    ctx.commit()

    assert ctx.view_svc.get("trial_a", "active").schema_name == "trial_a"
    assert ctx.view_svc.get("trial_b", "active").schema_name == "trial_b"


def test_get_missing_view_raises_not_found(ctx: AppContext, make_schema):
    make_schema("trial")
    ctx.commit()

    with pytest.raises(NotFoundError):
        ctx.view_svc.get("trial", "missing")


def test_list_all_returns_views_for_schema_only(ctx: AppContext, make_schema):
    make_schema("trial_a")
    make_schema("trial_b")
    ctx.commit()
    ctx.view_svc.create("trial_a", "view1")
    ctx.view_svc.create("trial_a", "view2")
    ctx.view_svc.create("trial_b", "view3")
    ctx.commit()

    names = {v.name for v in ctx.view_svc.list_all("trial_a")}
    assert names == {"view1", "view2"}


def test_update_view_renames_and_replaces_columns_filter_sort(
    ctx: AppContext, make_schema
):
    make_schema("trial", fields=[("subject", "string"), ("status", "string")])
    ctx.commit()
    ctx.view_svc.create("trial", "view1", columns=["subject"])
    ctx.commit()

    updated = ctx.view_svc.update(
        "trial",
        "view1",
        new_name="view1_renamed",
        columns=["status"],
        filter_tree={"field": "status", "op": "eq", "value": "x"},
        sort=[{"field": "status", "direction": "asc"}],
    )
    ctx.commit()

    assert updated.name == "view1_renamed"
    assert updated.columns == ["status"]
    assert updated.filter_tree == {"field": "status", "op": "eq", "value": "x"}
    assert updated.sort == [{"field": "status", "direction": "asc"}]

    fetched = ctx.view_svc.get("trial", "view1_renamed")
    assert fetched.columns == ["status"]


def test_update_view_omitting_a_field_leaves_it_unchanged(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()
    ctx.view_svc.create("trial", "view1", columns=["subject"])
    ctx.commit()

    updated = ctx.view_svc.update("trial", "view1")
    ctx.commit()

    assert updated.columns == ["subject"]


def test_update_view_clearing_filter_tree(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("status", "string")])
    ctx.commit()
    ctx.view_svc.create(
        "trial", "view1", filter_tree={"field": "status", "op": "eq", "value": "a"}
    )
    ctx.commit()

    updated = ctx.view_svc.update("trial", "view1", filter_tree=None)
    ctx.commit()

    assert updated.filter_tree is None


def test_update_view_rename_conflict_raises_already_exists(
    ctx: AppContext, make_schema
):
    make_schema("trial")
    ctx.commit()
    ctx.view_svc.create("trial", "view1")
    ctx.view_svc.create("trial", "view2")
    ctx.commit()

    with pytest.raises(AlreadyExistsError):
        ctx.view_svc.update("trial", "view1", new_name="view2")


def test_update_missing_view_raises_not_found(ctx: AppContext, make_schema):
    make_schema("trial")
    ctx.commit()

    with pytest.raises(NotFoundError):
        ctx.view_svc.update("trial", "missing", new_name="new")


def test_delete_view(ctx: AppContext, make_schema):
    make_schema("trial")
    ctx.commit()
    ctx.view_svc.create("trial", "view1")
    ctx.commit()

    ctx.view_svc.delete("trial", "view1")
    ctx.commit()

    with pytest.raises(NotFoundError):
        ctx.view_svc.get("trial", "view1")
    assert ctx.view_svc.list_all("trial") == []


def test_delete_missing_view_raises_not_found(ctx: AppContext, make_schema):
    make_schema("trial")
    ctx.commit()

    with pytest.raises(NotFoundError):
        ctx.view_svc.delete("trial", "missing")


def test_purging_schema_deletes_its_views(ctx: AppContext, make_schema):
    make_schema("trial")
    ctx.commit()
    ctx.view_svc.create("trial", "view1")
    ctx.commit()

    ctx.schema_svc.delete("trial")
    ctx.commit()
    ctx.schema_svc.purge("trial")
    ctx.commit()

    ctx.schema_svc.create("trial")
    ctx.commit()
    assert ctx.view_svc.list_all("trial") == []


# --- Single-hop reference-field joins ---


def _make_invoice_customer_schemas(ctx: AppContext, make_schema):
    make_schema("customer", fields=[("email", "string"), ("region", "string")])
    make_schema("invoice", fields=[("amount", "integer")])
    ctx.schema_svc.add_field(
        "invoice", "customer", "reference", restrictions={"schema": "customer"}
    )
    ctx.commit()


def test_create_view_accepts_single_hop_reference_join_column(
    ctx: AppContext, make_schema
):
    _make_invoice_customer_schemas(ctx, make_schema)

    view = ctx.view_svc.create(
        "invoice", "with_customer", columns=["amount", "customer.email"]
    )
    ctx.commit()

    assert view.columns == ["amount", "customer.email"]


def test_create_view_rejects_join_through_reference_list_field(
    ctx: AppContext, make_schema
):
    make_schema("customer", fields=[("email", "string")])
    make_schema("invoice")
    ctx.schema_svc.add_field(
        "invoice",
        "customers",
        "reference_list",
        restrictions={"schema": "customer"},
    )
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create("invoice", "bad", columns=["customers.email"])


def test_create_view_rejects_multi_hop_join_column(ctx: AppContext, make_schema):
    _make_invoice_customer_schemas(ctx, make_schema)
    ctx.schema_svc.add_field(
        "customer", "region_ref", "reference", restrictions={"schema": "customer"}
    )
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create(
            "invoice", "bad", columns=["customer.region_ref.email"]
        )


def test_create_view_rejects_join_through_non_reference_field(
    ctx: AppContext, make_schema
):
    make_schema("invoice", fields=[("amount", "integer")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create("invoice", "bad", columns=["amount.email"])


def test_create_view_rejects_join_through_reference_without_schema_restriction(
    ctx: AppContext, make_schema
):
    make_schema("customer", fields=[("email", "string")])
    make_schema("invoice")
    ctx.schema_svc.add_field("invoice", "customer", "reference")
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.create("invoice", "bad", columns=["customer.email"])


def test_create_view_rejects_unknown_join_target_field(ctx: AppContext, make_schema):
    _make_invoice_customer_schemas(ctx, make_schema)

    with pytest.raises(ValidationError):
        ctx.view_svc.create("invoice", "bad", columns=["customer.nonexistent"])


def test_update_view_accepts_join_column(ctx: AppContext, make_schema):
    _make_invoice_customer_schemas(ctx, make_schema)
    ctx.view_svc.create("invoice", "view1", columns=["amount"])
    ctx.commit()

    updated = ctx.view_svc.update(
        "invoice", "view1", columns=["amount", "customer.email"]
    )
    ctx.commit()

    assert updated.columns == ["amount", "customer.email"]


# --- resolve_rows: joining at query time ---


def test_resolve_rows_joins_reference_field(
    ctx: AppContext, make_schema, make_collection
):
    _make_invoice_customer_schemas(ctx, make_schema)
    make_collection("study")
    ctx.commit()
    customer = ctx.record_svc.add(
        "study", "customer", {"email": "a@example.com", "region": "west"}
    )
    invoice = ctx.record_svc.add(
        "study", "invoice", {"amount": 100, "customer": str(customer.id)}
    )
    ctx.commit()
    ctx.view_svc.create(
        "invoice", "with_customer", columns=["amount", "customer.email"]
    )
    ctx.commit()

    rows = ctx.view_svc.resolve_rows("invoice", "with_customer", [invoice])

    assert rows == [{"amount": 100, "customer.email": "a@example.com"}]


def test_resolve_rows_returns_none_for_unset_reference(
    ctx: AppContext, make_schema, make_collection
):
    _make_invoice_customer_schemas(ctx, make_schema)
    make_collection("study")
    ctx.commit()
    invoice = ctx.record_svc.add("study", "invoice", {"amount": 50})
    ctx.commit()
    ctx.view_svc.create(
        "invoice", "with_customer", columns=["amount", "customer.email"]
    )
    ctx.commit()

    rows = ctx.view_svc.resolve_rows("invoice", "with_customer", [invoice])

    assert rows == [{"amount": 50, "customer.email": None}]


# --- preview: live rows for an unsaved column/filter/sort selection ---


def test_preview_joins_and_filters_across_collections(
    ctx: AppContext, make_schema, make_collection
):
    _make_invoice_customer_schemas(ctx, make_schema)
    make_collection("study_a")
    make_collection("study_b")
    ctx.commit()
    customer = ctx.record_svc.add(
        "study_a", "customer", {"email": "a@example.com", "region": "west"}
    )
    ctx.record_svc.add(
        "study_a", "invoice", {"amount": 100, "customer": str(customer.id)}
    )
    ctx.record_svc.add(
        "study_b", "invoice", {"amount": 5, "customer": str(customer.id)}
    )
    ctx.commit()

    rows, total = ctx.view_svc.preview(
        "invoice",
        columns=["amount", "customer.email"],
        filter_tree={"field": "amount", "op": "gte", "value": 10},
    )

    assert total == 1
    assert rows == [{"amount": 100, "customer.email": "a@example.com"}]


def test_preview_sorts_by_joined_column(ctx: AppContext, make_schema, make_collection):
    _make_invoice_customer_schemas(ctx, make_schema)
    make_collection("study")
    ctx.commit()
    alice = ctx.record_svc.add(
        "study", "customer", {"email": "alice@example.com", "region": "west"}
    )
    bob = ctx.record_svc.add(
        "study", "customer", {"email": "bob@example.com", "region": "east"}
    )
    ctx.record_svc.add(
        "study", "invoice", {"amount": 1, "customer": str(bob.id)}
    )
    ctx.record_svc.add(
        "study", "invoice", {"amount": 2, "customer": str(alice.id)}
    )
    ctx.commit()

    rows, total = ctx.view_svc.preview(
        "invoice",
        columns=["amount", "customer.email"],
        sort=[{"field": "amount", "direction": "asc"}],
    )

    assert total == 2
    assert [r["customer.email"] for r in rows] == [
        "bob@example.com",
        "alice@example.com",
    ]


def test_preview_paginates_while_total_reflects_full_match(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("trial", fields=[("subject", "integer")])
    make_collection("study")
    ctx.commit()
    for i in range(5):
        ctx.record_svc.add("study", "trial", {"subject": i})
    ctx.commit()

    rows, total = ctx.view_svc.preview(
        "trial",
        columns=["subject"],
        sort=[{"field": "subject", "direction": "asc"}],
        limit=2,
        offset=1,
    )

    assert total == 5
    assert [r["subject"] for r in rows] == [1, 2]


def test_preview_rejects_unknown_column(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.preview("trial", columns=["nope"])


def test_preview_rejects_unknown_filter_field(ctx: AppContext, make_schema):
    make_schema("trial", fields=[("subject", "string")])
    ctx.commit()

    with pytest.raises(ValidationError):
        ctx.view_svc.preview(
            "trial", filter_tree={"field": "nope", "op": "eq", "value": "x"}
        )


def test_resolve_rows_returns_none_for_dangling_reference(
    ctx: AppContext, make_schema, make_collection
):
    import uuid

    _make_invoice_customer_schemas(ctx, make_schema)
    make_collection("study")
    ctx.commit()
    invoice = ctx.record_svc.add(
        "study", "invoice", {"amount": 50, "customer": str(uuid.uuid4())}
    )
    ctx.commit()
    ctx.view_svc.create(
        "invoice", "with_customer", columns=["amount", "customer.email"]
    )
    ctx.commit()

    rows = ctx.view_svc.resolve_rows("invoice", "with_customer", [invoice])

    assert rows == [{"amount": 50, "customer.email": None}]


# --- export: querying, filtering, sorting, and file bundling ---


def _file_ref(sha256: str, filename: str, size: int = 10) -> dict:
    return {"sha256": sha256, "filename": filename, "size": size}


def test_export_joins_filters_and_sorts(ctx: AppContext, make_schema, make_collection):
    _make_invoice_customer_schemas(ctx, make_schema)
    make_collection("study")
    ctx.commit()
    customer = ctx.record_svc.add(
        "study", "customer", {"email": "a@example.com", "region": "west"}
    )
    ctx.record_svc.add(
        "study", "invoice", {"amount": 300, "customer": str(customer.id)}
    )
    ctx.record_svc.add(
        "study", "invoice", {"amount": 100, "customer": str(customer.id)}
    )
    ctx.record_svc.add("study", "invoice", {"amount": 50})  # filtered out below
    ctx.commit()
    ctx.view_svc.create(
        "invoice",
        "big_orders",
        columns=["amount", "customer.email"],
        filter_tree={"field": "amount", "op": "gte", "value": 100},
        sort=[{"field": "amount", "direction": "asc"}],
    )
    ctx.commit()

    export = ctx.view_svc.export("invoice", "big_orders")

    assert export.rows == [
        {"amount": 100, "customer.email": "a@example.com"},
        {"amount": 300, "customer.email": "a@example.com"},
    ]
    assert export.file_entries == []


def test_export_spans_every_dataset_for_the_schema(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("trial", fields=[("subject", "string")])
    make_collection("study1")
    make_collection("study2")
    ctx.commit()
    ctx.record_svc.add("study1", "trial", {"subject": "S01"})
    ctx.record_svc.add("study2", "trial", {"subject": "S02"})
    ctx.commit()
    ctx.view_svc.create("trial", "all", columns=["subject"])
    ctx.commit()

    export = ctx.view_svc.export("trial", "all")

    assert {row["subject"] for row in export.rows} == {"S01", "S02"}


def test_export_bundles_file_columns_and_uses_resolved_filename(
    ctx: AppContext, make_schema, make_collection
):
    make_schema(
        "invoice",
        fields=[("invoice_number", "string"), ("scan", "file")],
    )
    ctx.schema_svc.update_field(
        "invoice", "scan", restrictions={"filename_template": "{invoice_number}.{ext}"}
    )
    make_collection("study")
    ctx.commit()
    record = ctx.record_svc.add(
        "study",
        "invoice",
        {"invoice_number": "INV-1", "scan": _file_ref("a" * 64, "upload.pdf")},
    )
    ctx.commit()
    ctx.view_svc.create("invoice", "with_scan", columns=["invoice_number", "scan"])
    ctx.commit()

    export = ctx.view_svc.export("invoice", "with_scan")

    assert export.rows == [{"invoice_number": "INV-1", "scan": "INV-1.pdf"}]
    assert len(export.file_entries) == 1
    path, ref = export.file_entries[0]
    assert path == f"{record.id}/INV-1.pdf"
    assert ref.sha256 == "a" * 64


def test_export_ignores_joined_file_columns_for_zip_bundling(
    ctx: AppContext, make_schema, make_collection
):
    make_schema("customer", fields=[("avatar", "file")])
    make_schema("invoice", fields=[("amount", "integer")])
    ctx.schema_svc.add_field(
        "invoice", "customer", "reference", restrictions={"schema": "customer"}
    )
    make_collection("study")
    ctx.commit()
    customer = ctx.record_svc.add(
        "study", "customer", {"avatar": _file_ref("b" * 64, "pic.png")}
    )
    ctx.record_svc.add(
        "study", "invoice", {"amount": 10, "customer": str(customer.id)}
    )
    ctx.commit()
    ctx.view_svc.create(
        "invoice", "with_avatar", columns=["amount", "customer.avatar"]
    )
    ctx.commit()

    export = ctx.view_svc.export("invoice", "with_avatar")

    assert export.file_entries == []
