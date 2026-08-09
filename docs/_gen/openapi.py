"""Writes the FastAPI OpenAPI spec to docs/reference/openapi.json before
mkdocs scans the docs tree.

This is an `on_pre_build` hook (registered under `hooks:` in mkdocs.yml)
rather than a `gen-files` script: neoteroi-mkdocs' `[OAD(...)]` directive on
http-api.md resolves its source path relative to the page's real docs_dir on
disk, but `gen-files` writes into an ephemeral temp directory that isn't
visible from there. Writing the real file before the file scan makes it a
normal page — resolvable by OAD and copied to the built site like any other
doc, so `reference/openapi.json` ends up downloadable too.

Importing `civex.server.app` is safe outside a civex project: `load_config()`
is try/excepted in `_init_observability()`, and no DB connection is opened.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from civex.server.app import create_app

_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "reference" / "openapi.json"


def on_pre_build(config: Any, **kwargs: Any) -> None:
    spec = create_app().openapi()
    _OUTPUT_PATH.write_text(json.dumps(spec, indent=2, sort_keys=True))
