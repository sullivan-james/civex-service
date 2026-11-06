"""A lone file stored in a `file_list` field (as `civex.match_files_to_records`
once wrote one) becomes a list of one; every other value stays as it is."""

from __future__ import annotations

import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

PREVIOUS = "c4d8e2f6a9b3"
UNDER_TEST = "bc183bbafef8"


def _config() -> Config:
    migrations_dir = Path(__file__).resolve().parents[2] / "src/civex/db/migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    return cfg


def test_a_lone_file_in_a_file_list_becomes_a_list(
    ctx, make_collection, make_record
) -> None:
    make_collection("study")
    ctx.schema_svc.create("unit")
    wavs = ctx.schema_svc.add_field("unit", "wavs", "file_list")
    one = ctx.schema_svc.add_field("unit", "one", "file")
    ref = ctx.file_svc.store_bytes(b"x", "a.wav").to_dict()
    bad = make_record("study", "unit", {"one": ref})
    good = make_record("study", "unit", {"wavs": [ref], "one": ref})
    ctx.commit()

    engine = ctx._session.get_bind()
    with engine.begin() as c:  # as the plugin left it, past the validation
        data = {str(wavs.id): ref, str(one.id): ref}
        c.execute(
            text("UPDATE records SET data = :d WHERE id = :id"),
            {"d": json.dumps(data), "id": bad.id.hex},
        )
    ctx.close()

    cfg = _config()
    for target in (command.downgrade, command.upgrade):
        with engine.connect() as c:
            cfg.attributes["connection"] = c
            target(cfg, PREVIOUS if target is command.downgrade else UNDER_TEST)
            c.commit()

    def stored(record) -> dict:
        with engine.connect() as c:
            raw = c.execute(
                text("SELECT data FROM records WHERE id = :id"), {"id": record.id.hex}
            ).scalar_one()
        return json.loads(raw) if isinstance(raw, str) else raw

    assert stored(bad)[str(wavs.id)] == [ref]
    assert stored(bad)[str(one.id)] == ref  # a `file` field holds one file
    assert stored(good)[str(wavs.id)] == [ref]
