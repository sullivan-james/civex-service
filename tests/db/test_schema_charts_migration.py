"""e4b9c1a7d2f6: kinds gain charts, and a saved analysis (a view with a
summary, from the unreleased Analytics work) becomes a chart card on the
Analytics page holding its definition and the records it was made for."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from civex.domain.dashboard import parse_cards

_PRE = "d7a3e9c5b2f1"
_POST = "e4b9c1a7d2f6"
_PAGE = "5d1e9a7c3b2f4c6e8a0d7f4b2e1c9a35"


def _config() -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src/civex/db/migrations"))
    return cfg


def _view(conn, schema: str, name: str, summary=None, tree=None) -> str:
    view = uuid.uuid4().hex
    conn.execute(
        text(
            "INSERT INTO views (id, schema_id, name, columns, sort, filter_tree, "
            "summary, files_layout, created_at) VALUES (:id, :s, :n, '[]', '[]', "
            ":f, :u, 'tree', :at)"
        ),
        {
            "id": view,
            "s": schema,
            "n": name,
            "f": json.dumps(tree) if tree else None,
            "u": json.dumps(summary) if summary else None,
            "at": f"2024-01-0{len(name) % 9 + 1}",
        },
    )
    return view


def _before(conn, cfg) -> str:
    cfg.attributes["connection"] = conn
    command.upgrade(cfg, _PRE)
    conn.commit()
    schema = uuid.uuid4().hex
    conn.execute(
        text(
            "INSERT INTO schemas (id, name, created_at) VALUES (:id, 'thing', '2024-01-01')"
        ),
        {"id": schema},
    )
    return schema


def _cards(conn) -> list[dict]:
    raw = conn.execute(text("SELECT cards FROM dashboards")).scalar()
    return json.loads(raw) if isinstance(raw, str) else raw


def test_analyses_become_chart_cards_and_views_stay_saved_filters(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'v.db'}")
    cfg = _config()
    collection = str(uuid.uuid4())
    tree = {"field": "depth", "op": "gt", "value": 2}
    with engine.connect() as conn:
        schema = _before(conn, cfg)
        placed = _view(
            conn,
            schema,
            "by site",
            {
                "group_by": ["site"],
                "measures": ["count", "mean:depth"],
                "sort": {"column": "site", "direction": "desc"},
                "show": "chart",
                "chart_measure": "mean:depth",
                "collection": collection,
                "within": None,
                "search": "reef",
            },
            tree,
        )
        loose = _view(conn, schema, "totals", {"group_by": [], "measures": ["count"],
                                               "show": "table"})  # fmt: skip
        _view(conn, schema, "plain", None, tree)
        gone = str(uuid.uuid4())
        conn.execute(
            text("INSERT INTO dashboards (id, cards, created_at) VALUES (:id, :c, '2024-01-01')"),
            {
                "id": _PAGE,
                "c": json.dumps(
                    [
                        {"id": "w", "kind": "widget", "size": "small", "widget": "storage"},
                        {"id": "mine", "kind": "analysis", "size": "wide",
                         "title": "Mine", "view": str(uuid.UUID(placed))},
                        {"id": "lost", "kind": "analysis", "size": "small", "view": gone},
                    ]
                ),
            },
        )  # fmt: skip
        conn.commit()

        command.upgrade(cfg, _POST)
        conn.commit()

        columns = inspect(conn)
        assert "summary" not in {c["name"] for c in columns.get_columns("views")}
        assert "charts" in {c["name"] for c in columns.get_columns("schemas")}
        # Every view is still there, as a saved filter.
        assert conn.execute(text("SELECT count(*) FROM views")).scalar() == 3
        cards = _cards(conn)
        assert [c["id"] for c in cards] == ["w", "mine", "v" + loose[:11]]
        schema_id = str(uuid.UUID(schema))
        assert cards[1] == {
            "id": "mine",
            "kind": "chart",
            "size": "wide",
            "title": "Mine",
            "chart": {
                "id": "mine",
                "group_by": ["site"],
                "measures": ["count", "mean:depth"],
                "sort": {"column": "site", "direction": "desc"},
                "chart_measure": "mean:depth",
            },
            "records": {
                "schema": schema_id,
                "collection": collection,
                "search": "reef",
                "filter": tree,
            },
        }
        assert cards[2]["title"] == "totals" and cards[2]["chart"]["show"] == "table"
        assert cards[2]["records"] == {"schema": schema_id}
        # What it wrote is what the page reads and would write again.
        assert [c.to_dict() for c in parse_cards(cards)] == cards


def test_an_analysis_goes_on_a_page_nobody_had_edited(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'n.db'}")
    cfg = _config()
    with engine.connect() as conn:
        schema = _before(conn, cfg)
        _view(conn, schema, "by site", {"group_by": ["site"], "measures": ["count"]})
        conn.commit()
        command.upgrade(cfg, _POST)
        conn.commit()
        cards = _cards(conn)
        assert [c["kind"] for c in cards] == ["widget"] * 11 + ["chart"]
        assert [c.to_dict() for c in parse_cards(cards)] == cards


def test_a_project_with_no_analyses_keeps_an_unedited_page(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}")
    cfg = _config()
    with engine.connect() as conn:
        schema = _before(conn, cfg)
        _view(conn, schema, "plain")
        conn.commit()
        command.upgrade(cfg, _POST)
        conn.commit()
        assert conn.execute(text("SELECT count(*) FROM dashboards")).scalar() == 0
        conn.execute(text("UPDATE schemas SET charts = '[]'"))
        conn.commit()
