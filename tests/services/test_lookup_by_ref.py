"""`lookup(ref)` finds a live schema or collection by its id or its name: the
one rule behind every `/{name_or_id}` route, so callers don't reach into
repositories."""

from __future__ import annotations

import uuid

import pytest

from civex.context import AppContext
from civex.domain.exceptions import NotFoundError


def test_a_collection_by_name_or_id(ctx: AppContext, make_collection):
    study = make_collection("study")
    assert ctx.dataset_svc.lookup("study").id == study.id
    assert ctx.dataset_svc.lookup(str(study.id)).name == "study"


def test_a_schema_by_name_or_id(ctx: AppContext, make_schema):
    trial = make_schema("trial")
    assert ctx.schema_svc.lookup("trial").id == trial.id
    assert ctx.schema_svc.lookup(str(trial.id)).name == "trial"


def test_unknown_or_deleted_is_not_found(ctx: AppContext, make_collection, make_schema):
    make_collection("study")
    make_schema("trial")
    ctx.dataset_svc.delete("study")
    ctx.schema_svc.delete("trial")
    ctx.commit()
    for lookup in (ctx.dataset_svc.lookup, ctx.schema_svc.lookup):
        with pytest.raises(NotFoundError):
            lookup(str(uuid.uuid4()))
        with pytest.raises(NotFoundError):
            lookup("nothing")
    with pytest.raises(NotFoundError):
        ctx.dataset_svc.lookup("study")
    with pytest.raises(NotFoundError):
        ctx.schema_svc.lookup("trial")
