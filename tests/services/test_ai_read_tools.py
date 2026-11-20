"""Ask AI's analysis tools: query_records with a filter tree, collection,
`within` and sort; summarise_records over RecordService.summarise; and
describe_schema. Each tool's `run` through the registry's dispatch, as the
chat calls it; no model is involved."""

from __future__ import annotations

import json

import pytest

from civex.context import AppContext
from civex.domain import permissions
from civex.services.ai.tools.base import AiToolContext
from civex.services.ai.tools.registry import dispatch


def _call(ctx: AppContext, tool: str, **tool_input):
    tool_ctx = AiToolContext(
        schema_svc=ctx.schema_svc,
        dataset_svc=ctx.dataset_svc,
        record_svc=ctx.record_svc,
        job_svc=ctx.job_svc,
        workflow_svc=ctx.workflow_svc,
        plugin_svc=ctx.plugin_svc,
        _app_ctx=ctx,
    )
    return json.loads(dispatch(tool, tool_input, tool_ctx))


@pytest.fixture()
def survey(ctx: AppContext, make_schema, make_collection, make_record):
    make_schema("site", fields=[("region", "string"), ("elevation", "integer")])
    make_schema(
        "sample",
        parent="site",
        fields=[("label", "string"), ("depth", "float"), ("taken", "date")],
    )
    ctx.schema_svc.update_field("sample", "depth", restrictions={"unit": "m"})
    ctx.schema_svc.update_field(
        "site", "region", restrictions={"choices": ["north", "south"]}
    )
    ctx.commit()
    make_collection("survey")
    make_collection("pilot")
    north = make_record("survey", "site", {"region": "north", "elevation": 10})
    south = make_record("survey", "site", {"region": "south", "elevation": 30})
    for parent, label, depth, taken in [
        (north, "a", 1.0, "2019-06-14"),
        (north, "b", 3.0, "2019-07-01"),
        (south, "c", 12.0, "2020-01-02"),
        (south, "d", 8.0, "2020-01-05"),
    ]:
        make_record(
            "survey",
            "sample",
            {"label": label, "depth": depth, "taken": taken},
            parent_record_id=str(parent.id),
        )
    other = make_record("pilot", "site", {"region": "north"})
    make_record(
        "pilot",
        "sample",
        {"label": "p", "depth": 100.0},
        parent_record_id=str(other.id),
    )
    return {"north": north, "south": south}


# --- query_records ---------------------------------------------------------


def test_query_records_applies_a_filter_tree(ctx, survey) -> None:
    result = _call(
        ctx,
        "query_records",
        schema="sample",
        filter={"field": "depth", "op": "gt", "value": 2},
        sort=[{"field": "depth", "direction": "desc"}],
    )
    assert result["total"] == "4"
    assert [r["data"]["label"] for r in result["records"]] == ["p", "c", "d", "b"]


def test_query_records_filters_on_a_field_of_a_kind_above(ctx, survey) -> None:
    result = _call(
        ctx,
        "query_records",
        schema="sample",
        collection="survey",
        filter={
            "and": [
                {"field": "region", "schema": "site", "op": "eq", "value": "north"},
                {"field": "depth", "op": "gte", "value": 2},
            ]
        },
    )
    assert result["total"] == "1"
    (record,) = result["records"]
    assert record["data"]["label"] == "b"
    assert record["collection"] == "survey"


def test_query_records_takes_the_filter_as_json_text(ctx, survey) -> None:
    result = _call(
        ctx,
        "query_records",
        schema="sample",
        count_only=True,
        filter=json.dumps({"field": "label", "op": "in", "value": ["a", "p"]}),
    )
    assert result == {"total": "2"}


def test_query_records_narrows_to_a_collection_and_within(ctx, survey) -> None:
    assert _call(
        ctx, "query_records", schema="sample", collection="pilot", count_only=True
    ) == {"total": "1"}
    within = _call(
        ctx,
        "query_records",
        schema="sample",
        within=str(survey["south"].id),
        count_only=True,
    )
    assert within == {"total": "2"}


def test_a_bad_filter_comes_back_as_an_error_the_model_can_read(ctx, survey) -> None:
    unknown_op = _call(
        ctx,
        "query_records",
        schema="sample",
        filter={"field": "depth", "op": "bigger", "value": 2},
    )
    assert unknown_op["status"] == "error"
    assert "bigger" in unknown_op["message"]

    unknown_field = _call(
        ctx,
        "query_records",
        schema="sample",
        filter={"field": "colour", "op": "eq", "value": "red"},
    )
    assert unknown_field["status"] == "error"
    assert "colour" in unknown_field["message"]

    not_json = _call(ctx, "query_records", schema="sample", filter="{depth > 2")
    assert not_json["status"] == "error"
    assert "JSON" in not_json["message"]


def test_query_records_unknown_collection_is_an_error(ctx, survey) -> None:
    result = _call(ctx, "query_records", schema="sample", collection="ghost")
    assert result["status"] == "error"
    assert "ghost" in result["message"]


# --- summarise_records -----------------------------------------------------


def test_summarise_records_groups_by_a_kind_above(ctx, survey) -> None:
    result = _call(
        ctx,
        "summarise_records",
        schema="sample",
        collection="survey",
        group_by=["site.region"],
        measures=["count", "mean:depth", "max:depth"],
    )
    assert result["columns"] == [
        "Site Region",
        "Records",
        "Average Depth (m)",
        "Largest Depth (m)",
    ]
    assert result["rows"] == [["north", 2, 2.0, 3.0], ["south", 2, 10.0, 12.0]]
    assert result["total"] == ["Total", 4, 6.0, 12.0]
    assert result["truncated"] is False
    assert result["units"] == {"Average Depth (m)": "m", "Largest Depth (m)": "m"}


def test_summarise_records_with_a_filter_and_a_date_period(ctx, survey) -> None:
    result = _call(
        ctx,
        "summarise_records",
        schema="sample",
        filter={"field": "depth", "op": "lt", "value": 50},
        group_by=["taken:year"],
    )
    assert result["rows"] == [["2019", 2], ["2020", 2]]
    assert result["total"] == ["Total", 4]


def test_summarise_records_caps_the_groups_it_returns(ctx, survey) -> None:
    result = _call(
        ctx, "summarise_records", schema="sample", group_by=["label"], limit=2
    )
    assert len(result["rows"]) == 2
    assert result["truncated"] is True
    assert result["total"] == ["Total", 5]


def test_summarise_records_refuses_a_measure_the_type_does_not_allow(
    ctx, survey
) -> None:
    result = _call(ctx, "summarise_records", schema="sample", measures=["mean:label"])
    assert result["status"] == "error"
    assert "mean" in result["message"] and "label" in result["message"]


def test_summarise_records_needs_read(ctx, survey) -> None:
    ctx.record_svc._permissions = permissions.Permissions.nothing()
    result = _call(ctx, "summarise_records", schema="sample")
    assert result["status"] == "error"
    assert "may not" in result["message"]


# --- describe_schema -------------------------------------------------------


def test_describe_schema_lists_fields_with_what_they_allow(ctx, survey) -> None:
    result = _call(ctx, "describe_schema", schema="sample")
    assert result["inside"] == ["site"]
    assert "contains" not in result
    fields = {f["name"]: f for f in result["fields"]}
    assert fields["depth"]["type"] == "float"
    assert fields["depth"]["unit"] == "m"
    assert "mean" in fields["depth"]["measures"]
    assert fields["depth"]["group_by"] == ["value", "ranges"]
    assert fields["taken"]["group_by"] == ["value", "year", "month", "week", "day"]
    assert "mean" not in fields["label"]["measures"]
    assert fields["region"]["from"] == "site"
    assert fields["region"]["choices"] == ["north", "south"]

    site = _call(ctx, "describe_schema", schema="site")
    assert site["contains"] == ["sample"]
    assert "inside" not in site


def test_describe_schema_unknown_is_an_error(ctx) -> None:
    result = _call(ctx, "describe_schema", schema="ghost")
    assert result["status"] == "error"
    assert "ghost" in result["message"]
