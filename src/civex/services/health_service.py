"""What `civex doctor` checks, and the repair, in one place.

The command and the app's Health page both call `check_health` and
`repair_database`, and both show the same `Problem` list, so they can't say
different things about one project. Like `db_service` this works without an
`AppContext` for the parts that must keep working when the database is
missing something: a context would trip over it.

Machine-bound checks follow the host's features (`domain.features`): the
install checks need `UPDATES` (a civex install on this machine), the files
left on drives need `VOLUMES`. A host that lacks them gets neither.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from civex.config import PartitionLayout
from civex.domain import features as features_
from civex.domain.exceptions import ValidationError
from civex.install_check import Check, run_install_checks
from civex.project import Project
from civex.services.sync_lock import sync_running

Severity = Literal["ok", "warn", "fail"]

# What the list of lacking tables and columns is cut to in one sentence.
_SHOWN = 8


class RepairRefused(ValidationError):
    """Repair was not started: nothing was changed."""


@dataclass(frozen=True)
class Problem:
    """One thing that is wrong, in plain words. `fix` says what to do about it
    (empty when nothing can be done here). `kind` names the check, so a page
    can group them."""

    kind: str
    severity: Severity
    message: str
    fix: str = ""
    items: tuple[str, ...] = ()


@dataclass
class HealthReport:
    install: list[Check] | None  # None: this host has no install to check
    structure: list[str]  # tables and columns the database lacks
    dangling: list[dict] = field(default_factory=list)
    orphans: list = field(default_factory=list)  # first few, with what is above
    orphan_total: int = 0
    left_on_drives: int = 0
    bucket: str | None = None
    data_checked: bool = False  # False: the database lacks structure

    def problems(self) -> list[Problem]:
        """Everything wrong, in the order a person should deal with it."""
        out: list[Problem] = []
        if self.install is not None:
            for check in self.install:
                if check.status != "ok":
                    out.append(
                        Problem(
                            "install",
                            check.status,
                            f"{check.name}: {check.detail}",
                            check.fix,
                        )
                    )
        if self.structure:
            shown = ", ".join(self.structure[:_SHOWN]) + (
                " …" if len(self.structure) > _SHOWN else ""
            )
            out.append(
                Problem(
                    "database",
                    "fail",
                    "The database is stamped as up to date but lacks what this "
                    f"civex expects: {shown}",
                    "Repair adds what is missing, after backing the database up.",
                    tuple(self.structure),
                )
            )
        if self.left_on_drives:
            out.append(
                Problem(
                    "files",
                    "warn",
                    f"{self.left_on_drives:,} file(s) are recorded on drives, but "
                    f"this project keeps its files in the bucket '{self.bucket}', "
                    "so they can't be reached.",
                    "Take [store.s3] out of _civex/config.toml to reach them "
                    "again; civex doesn't move files between drives and a bucket.",
                )
            )
        if self.dangling:
            out.append(
                Problem(
                    "references",
                    "fail",
                    f"Found {len(self.dangling)} dangling reference(s).",
                    "",
                    tuple(
                        f"{d['schema_name']} record {d['record_id']} field "
                        f"'{d['field_name']}' -> missing record "
                        f"{d['dangling_target_id']}"
                        for d in self.dangling
                    ),
                )
            )
        if self.orphan_total:
            lines = []
            for o in self.orphans:
                top = o.above[0]
                lines.append(
                    f"{o.record.schema_name} {o.record.natural_name or ''} "
                    f"{str(o.record.id)[:8]} under deleted {top.schema_name} "
                    f"{top.natural_name or ''} {str(top.id)[:8]}".replace("  ", " ")
                )
            if self.orphan_total > len(self.orphans):
                lines.append(f"...and {self.orphan_total - len(self.orphans)} more")
            out.append(
                Problem(
                    "orphans",
                    "fail",
                    f"Found {self.orphan_total} record(s) under a deleted record "
                    "(out of sight, and refused by a sync server).",
                    "Put one back in place with `civex record restore-above <id>`, "
                    "or delete it.",
                    tuple(lines),
                )
            )
        return out

    @property
    def failed(self) -> bool:
        return any(p.severity == "fail" for p in self.problems())

    @property
    def repairable(self) -> bool:
        return bool(self.structure)


def _engine(project: Project) -> tuple[Engine, bool]:
    """The project's engine, and whether this call made it (and must dispose)."""
    if project.engine is not None:
        return project.engine, False
    return create_engine(project.config.db.url), True


def check_health(project: Project) -> HealthReport:
    """Run every check this project's host offers."""
    from civex.context import build_context
    from civex.db.migrate import missing_structure

    features = project.features
    install = (
        run_install_checks() if features_.enabled(features, features_.UPDATES) else None
    )

    engine, owned = _engine(project)
    try:
        lacking = missing_structure(engine)
    finally:
        if owned:
            engine.dispose()
    report = HealthReport(install=install, structure=lacking)
    if lacking:
        return report  # the data checks would trip over what is missing

    ctx = build_context(project)
    try:
        report.dangling = ctx.record_svc.find_dangling_references()
        report.orphans, report.orphan_total = ctx.record_svc.orphans(50)
        if features_.enabled(features, features_.VOLUMES):
            stranded = ctx.bucket_svc.status()
            report.left_on_drives = stranded.left_on_drives
            report.bucket = stranded.bucket
    finally:
        ctx.close()
    report.data_checked = True
    return report


# -- repair -----------------------------------------------------------------


@dataclass(frozen=True)
class RepairResult:
    backup: Path
    added: list[str]  # the tables and columns that were missing


def backups_dir(project: Project) -> Path:
    return project.config.civex_dir / "backups"


def _stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def backup_database(project: Project) -> Path:
    """Copy the database into `_civex/backups/` and return where. SQLite: a
    consistent copy of the file. PostgreSQL: `pg_dump` (on PATH, else inside
    the project's own Docker container). Raises `RepairRefused` when no backup
    can be made: a repair never runs without one."""
    url = make_url(project.config.db.url)
    target_dir = backups_dir(project)
    target_dir.mkdir(parents=True, exist_ok=True)
    if url.get_backend_name() == "sqlite":
        source = Path(url.database or "")
        if not source.is_file():
            raise RepairRefused(
                "The database file can't be found, so it can't be backed up."
            )
        target = target_dir / f"civex-{_stamp()}.db"
        src = sqlite3.connect(str(source))
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return target

    target = target_dir / f"civex-{_stamp()}.sql"
    pg_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    if shutil.which("pg_dump"):
        command = ["pg_dump", "--no-owner", "--file", str(target), pg_url]
    elif project.config.db.docker_managed:
        from civex.docker_manager import container_name

        command = [
            "docker",
            "exec",
            container_name(project.config.project_root.name),
            "pg_dump",
            "-U",
            url.username or "postgres",
            url.database or "postgres",
        ]
    else:
        raise RepairRefused(
            "Making a backup of this database needs `pg_dump`, which isn't "
            "installed here. Back the database up yourself, then repair."
        )
    try:
        if command[0] == "docker":
            with open(target, "wb") as out:
                done = subprocess.run(
                    command, stdout=out, stderr=subprocess.PIPE, timeout=3600
                )
        else:
            done = subprocess.run(command, capture_output=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as e:
        target.unlink(missing_ok=True)
        raise RepairRefused(f"The backup could not be made: {e}") from None
    if done.returncode != 0:
        target.unlink(missing_ok=True)
        raise RepairRefused(
            "The backup could not be made, so nothing was changed. "
            + done.stderr.decode(errors="replace").strip()[-300:]
        )
    return target


def _add_missing(engine: Engine, missing: list[str]) -> None:
    """Create each missing table and add each missing column. A column that
    must have a value but has no default is added as allowing none: rows that
    already exist can't be given one."""
    from civex.db.models import Base

    tables = {t.name: t for t in Base.metadata.sorted_tables}
    whole = [m for m in missing if "." not in m]
    for name in whole:
        tables[name].create(engine, checkfirst=True)
    with engine.begin() as conn:
        for item in missing:
            if "." not in item:
                continue
            table_name, column_name = item.split(".", 1)
            have = {c["name"] for c in inspect(conn).get_columns(table_name)}
            if column_name in have:
                continue
            column = tables[table_name].c[column_name]
            ddl = column.type.compile(dialect=engine.dialect)
            sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {ddl}'
            if column.server_default is not None:
                default = column.server_default.arg  # type: ignore[attr-defined]
                if isinstance(default, str):
                    literal = "'" + default.replace("'", "''") + "'"
                else:
                    literal = str(
                        default.compile(
                            dialect=engine.dialect,
                            compile_kwargs={"literal_binds": True},
                        )
                    )
                sql += f" DEFAULT {literal}"
                if not column.nullable:
                    sql += " NOT NULL"
            conn.execute(text(sql))
    if (
        engine.dialect.name == "sqlite"
        and "audit_log" in inspect(engine).get_table_names()
    ):
        from importlib import import_module

        history = import_module(
            "civex.db.migrations.versions.e8b4f2c6a917_history_delta_and_write_order"
        )
        with engine.begin() as conn:
            conn.execute(text(history._SQLITE_TRIGGER))


def repair_database(project: Project) -> RepairResult:
    """Back the database up, then add the tables and columns it lacks.
    Idempotent: with nothing missing it changes nothing (and still says where
    the backup is). Refused, changing nothing, while a sync is running."""
    from civex.db.migrate import ensure_schema_current, missing_structure

    if sync_running(project.config.civex_dir):
        raise RepairRefused(
            "Syncing is running right now. Repair when it has finished."
        )
    backup = backup_database(project)
    engine, owned = _engine(project)
    try:
        ensure_schema_current(engine, PartitionLayout.for_config(project.config.db))
        missing = missing_structure(engine)
        if missing:
            _add_missing(engine, missing)
        left = missing_structure(engine)
        if left:
            raise RepairRefused(
                "Some of what is missing could not be added: "
                + ", ".join(left[:_SHOWN])
            )
    finally:
        if owned:
            engine.dispose()
    return RepairResult(backup=backup, added=missing)
