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
