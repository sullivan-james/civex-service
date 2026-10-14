"""The app's page, for wherever it is served.

The built frontend is one `index.html` whose assets are addressed from its
`<base href>`. `civex serve` serves it at `/`; a host serving many projects
(the hub) serves the same build at `/p/<owner>/<project>/`, and may hand the
app a boot object (`window.__CIVEX__`: where to sign in again, which
extensions to load; `frontend/src/utils/host.ts`). Both come through
`render_app_page`, so the page is made one way.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_BASE = re.compile(r"<base\s+href=\"[^\"]*\"\s*/?>", re.IGNORECASE)


@lru_cache(maxsize=4)
def _template(path: Path, mtime: float) -> str:
    return path.read_text(encoding="utf-8")


def _script_json(value: Any) -> str:
    """JSON that can sit inside a `<script>`: nothing in it can close the
    element or start a comment, whatever a value holds."""
    text = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def normalise_base(base: str) -> str:
    """`/p/acme/survey` → `/p/acme/survey/`: a base names a folder, so the
    page's relative assets resolve inside it."""
    if not base.startswith("/"):
        raise ValueError(f"A base path starts with '/': {base!r}")
    return base if base.endswith("/") else base + "/"


def render_app_page(
    dist: Path, *, base: str = "/", boot: dict[str, Any] | None = None
) -> str:
    """`dist/index.html` served at `base`, with `boot` as `window.__CIVEX__`
    when given (`login_url`, `extensions`; whatever else a host's extensions
    read). The page is read once per build."""
    index = dist / "index.html"
    page = _template(index, index.stat().st_mtime)
    tag = f'<base href="{normalise_base(base)}" />'
    page, found = _BASE.subn(tag, page, count=1)
    if not found:  # a build from before the app had one
        page = page.replace("<head>", f"<head>\n    {tag}", 1)
    if boot:
        script = f"<script>window.__CIVEX__ = {_script_json(boot)}</script>"
        page = page.replace("</head>", f"    {script}\n  </head>", 1)
    return page
