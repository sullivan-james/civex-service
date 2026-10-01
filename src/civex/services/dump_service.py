"""Writing a project's dump file: schemas, collections, records, workflows and
plugins as one YAML document.

Shared by `civex dump` and `GET /dump`. Records are paged out of the database
and written as they arrive, so a dump's size is bounded by disk, not memory,
and no collection is cut short; the sections concatenate to the same mapping a
single `yaml.dump` of the whole document would produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import yaml

from civex import __version__
from civex.services.dataset_service import DatasetService
from civex.services.record_service import RecordService
from civex.services.schema_service import SchemaService


# Records written per commit while restoring -- a commit per record made the
# restore of a large dump dominated by fsyncs.
RESTORE_BATCH = 1000


@dataclass
class DumpCounts:
    schemas: int = 0
    datasets: int = 0
    records: int = 0
    workflows: int = 0
    plugins: int = 0
    file_refs: int = 0


def sort_schemas(schemas: list[dict]) -> list[dict]:
    """Topological sort — parents before children."""
    by_name = {s["name"]: s for s in schemas}
    result: list[dict] = []
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        parent = by_name[name].get("parent")
        if parent and parent in by_name:
            visit(parent)
        result.append(by_name[name])

    for s in schemas:
        visit(s["name"])
    return result


def export_schemas(schema_svc: SchemaService) -> list[dict]:
    schemas = schema_svc.list_all()
    names = {s.id: s.name for s in schemas}
    return sort_schemas(
        [
            {
                "name": s.name,
                "label": s.label,
                "description": s.description,
                "parent": names.get(s.parent_id) if s.parent_id else None,
                "fields": [
                    {
                        "name": f.name,
                        "label": f.label,
                        "type": f.dtype,
                        "required": f.required,
                    }
                    for f in s.fields
                ],
            }
            for s in schemas
        ]
    )


def _yaml(doc: Any) -> str:
    return yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _files(directory: Path, *patterns: str) -> list[dict[str, str]]:
    if not directory.exists():
        return []
    return [
        {"filename": p.name, "content": p.read_text(encoding="utf-8")}
        for pattern in patterns
        for p in sorted(directory.glob(pattern))
    ]


def write_dump(
    out: TextIO,
    schema_svc: SchemaService,
    dataset_svc: DatasetService,
    record_svc: RecordService,
    civex_dir: Path | None,
    include_data: bool = True,
    include_workflows: bool = True,
) -> DumpCounts:
    """Write the dump to `out`. `civex_dir` is where workflows/ and plugins/
    live (None leaves them out)."""
    counts = DumpCounts()
    schemas_out = export_schemas(schema_svc)
    datasets = dataset_svc.list_all(with_count=False) if include_data else []
    datasets_out = [
        {
            "name": d.name,
            "description": d.description,
            "scope": d.scope,
            "schemas": d.schemas,
        }
        for d in datasets
    ]
    counts.schemas, counts.datasets = len(schemas_out), len(datasets_out)
    out.write(
        _yaml(
            {
                "civex_version": __version__,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "schemas": schemas_out,
                "datasets": datasets_out,
            }
        )
    )

    wrote_records = False
    for dataset in datasets:
        for page in record_svc.iter_find(dataset.name):
            chunk = []
            for record in page:
                rec: dict[str, Any] = {
                    "dataset": dataset.name,
                    "schema": record.schema_name,
                    "data": record.data,
                }
                if record.parent_record_id:
                    rec["parent_record_id"] = str(record.parent_record_id)
                chunk.append(rec)
                counts.file_refs += sum(
                    1
                    for v in record.data.values()
                    if isinstance(v, dict) and "sha256" in v
                )
            if not wrote_records:
                out.write("records:\n")
                wrote_records = True
            counts.records += len(chunk)
            out.write(_yaml(chunk))
    if not wrote_records:
        out.write("records: []\n")

    workflows = (
        _files(civex_dir / "workflows", "*.yaml", "*.yml")
        if civex_dir and include_workflows
        else []
    )
    plugins = (
        _files(civex_dir / "plugins", "*.py") if civex_dir and include_workflows else []
    )
    counts.workflows, counts.plugins = len(workflows), len(plugins)
    out.write(_yaml({"workflows": workflows, "plugins": plugins}))
    return counts
