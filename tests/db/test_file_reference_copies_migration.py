"""f7b3d9e2a6c4: each record's file points at one copy.

Existing rows are pointed at a copy by the migration: for each collection, the
drive holding most of its files (ties by name), so a collection whose files
were all copied onto one drive reads as wholly there, not split by whichever
copy sorts first. A file with no copy here stays unpointed."""

from __future__ import annotations

import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

_PRE = "e6a2c8f4d1b7"
_POST = "f7b3d9e2a6c4"
_WHEN = "2024-01-01 00:00:00"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def _id() -> str:
    return str(uuid.uuid4())


def test_each_collection_points_at_the_drive_holding_most_of_its_files(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'c.db'}")
    cfg = _config()
    schema, one, two = _id(), _id(), _id()
    sha = {name: name * 64 for name in "abcd"}
    refs: dict[tuple[str, str], str] = {}  # (collection, file) -> reference id

    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, _PRE)
        conn.commit()
        conn.execute(
            text("INSERT INTO schemas (id, name, created_at) VALUES (:i, 'doc', :w)"),
            {"i": schema, "w": _WHEN},
        )
        for cid, name in ((one, "one"), (two, "two")):
            conn.execute(
                text("INSERT INTO datasets (id, name, created_at) VALUES (:i, :n, :w)"),
                {"i": cid, "n": name, "w": _WHEN},
            )
        # "one" uses a, b, c: all on vol-b, and c also on vol-a. "two" uses c
        # (on both: a tie, broken by name) and d, which isn't here at all.
        for f, volumes in (
            ("a", ["vol-b"]),
            ("b", ["vol-b"]),
            ("c", ["vol-a", "vol-b"]),
        ):
            for v in volumes:
                conn.execute(
                    text(
                        "INSERT INTO stored_objects (sha256, volume, size, created_at) "
                        "VALUES (:s, :v, 1, :w)"
                    ),
                    {"s": sha[f], "v": v, "w": _WHEN},
                )
        for cid, files in ((one, "abc"), (two, "cd")):
            for f in files:
                record = _id()
                conn.execute(
                    text(
                        "INSERT INTO records (id, dataset_id, schema_id, data, "
                        "created_at, updated_at) VALUES (:i, :d, :s, '{}', :w, :w)"
                    ),
                    {"i": record, "d": cid, "s": schema, "w": _WHEN},
                )
                ref = _id()
                refs[(cid, f)] = ref
                conn.execute(
                    text(
                        "INSERT INTO file_references (id, sha256, record_id) "
                        "VALUES (:i, :s, :r)"
                    ),
                    {"i": ref, "s": sha[f], "r": record},
                )
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()

        pointed = {
            row[0]: row[1]
            for row in conn.execute(text("SELECT id, volume FROM file_references"))
        }

    def at(cid: str, f: str) -> str | None:
        return pointed[refs[(cid, f)]]

    assert [at(one, f) for f in "abc"] == ["vol-b", "vol-b", "vol-b"]
    assert at(two, "c") == "vol-a"  # a tie: first by name
    assert at(two, "d") is None  # no copy here yet
