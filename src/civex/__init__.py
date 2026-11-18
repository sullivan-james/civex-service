from __future__ import annotations

import os
from importlib.metadata import version, PackageNotFoundError
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from civex.context import AppContext

try:
    __version__ = version("civex")
except PackageNotFoundError:
    __version__ = "0.0.0.dev"

from civex._sdk_repair import repair_sdk_if_needed  # noqa: E402

repair_sdk_if_needed()


def open(path: str | os.PathLike[str] | None = None) -> AppContext:  # noqa: A001
    """Open the civex project at `path` (or above it; the current directory by
    default) in this process, with no server: the services the CLI and the
    app use (`schema_svc`, `dataset_svc`, `record_svc`, `file_svc`,
    `view_svc`, `file_access_svc`, ...). See `civex.context.open_project`.

        with civex.open("~/fieldwork") as project:
            for record in project.record_svc.find("survey-2024", schema_name="sample"):
                print(record.data)
    """
    from civex.context import open_project

    return open_project(path)
