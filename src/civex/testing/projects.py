"""Fresh projects for a test, each in a folder of its own."""

from __future__ import annotations

from pathlib import Path

from civex.config import load_config_at
from civex.context import AppContext, build_local_context
from civex.project import scaffold_project


class Projects:
    """`project("laptop")` -> a context on a new, empty project of that name
    under `root` (SQLite beside it unless `db_url` says otherwise); `close()`
    closes every context made. The `project` fixture of `tests/sync`."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._made: list[AppContext] = []

    def __call__(self, name: str, db_url: str | None = None) -> AppContext:
        root = self._root / name
        scaffold_project(
            root, db_url=db_url or f"sqlite:///{(root / 'civex.db').as_posix()}"
        )
        ctx = build_local_context(load_config_at(root))
        self._made.append(ctx)
        return ctx

    def close(self) -> None:
        for ctx in self._made:
            ctx.close()
        self._made.clear()
