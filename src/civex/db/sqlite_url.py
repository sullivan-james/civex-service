"""SQLite database URLs and file paths, converted the same way on every OS.

`urlparse(url).path` is wrong for `sqlite:///C:/data/x.db` (it yields
`/C:/data/x.db`, which Windows rejects), so URLs go through SQLAlchemy."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def sqlite_file(url: str) -> Path:
    database = make_url(url).database
    if not database:
        raise ValueError(f"{url!r} does not name a SQLite file")
    return Path(database)
