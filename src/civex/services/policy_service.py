"""Software license text + org-authored data/governance policy documents.

Single source of truth for both, shared by the `civex license`/`civex
policy` CLI commands and the /api/legal HTTP routes so neither has to
duplicate the reading logic (same split as workflow_service.py).

Policies are markdown files an admin drops in _civex/policies/ -- content
this deployment authors and edits itself, not tied to a code change. The
license is this build's own LICENSE file, resolved via the same
package-installed / PyInstaller-bundle / dev-source-tree fallback chain as
server/app.py's _find_dist(), since civex ships through all three.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from civex.domain.exceptions import NotFoundError, ValidationError

_SAFE_STEM = re.compile(r"^[\w-]+$")


@dataclass
class PolicyDTO:
    stem: str
    title: str
    content: str


def _find_license_text() -> str:
    # 1. Package-installed copy, if a release process ever bundles one
    #    alongside the package (mirrors server/app.py's _find_dist()).
    p = Path(__file__).resolve().parents[1] / "LICENSE"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    # 2. PyInstaller one-file bundle.
    if getattr(sys, "frozen", False):
        p = Path(getattr(sys, "_MEIPASS")) / "LICENSE"
        if p.is_file():
            return p.read_text(encoding="utf-8")
    # 3. Development source tree.
    p = Path(__file__).resolve().parents[3] / "LICENSE"
    if p.is_file():
        return p.read_text(encoding="utf-8")
    raise NotFoundError("LICENSE file not found")


def _title_from(content: str, stem: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return stem.replace("-", " ").replace("_", " ").title()


class PolicyService:
    def __init__(self, civex_dir: Path) -> None:
        self._dir = civex_dir / "policies"

    def license_text(self) -> str:
        return _find_license_text()

    def list(self) -> list[PolicyDTO]:
        if not self._dir.is_dir():
            return []
        out = []
        for path in sorted(self._dir.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            out.append(PolicyDTO(path.stem, _title_from(content, path.stem), content))
        return out

    def get(self, stem: str) -> PolicyDTO:
        if not _SAFE_STEM.match(stem):
            raise ValidationError(
                "stem must contain only letters, numbers, hyphens, and underscores"
            )
        path = self._dir / f"{stem}.md"
        if not path.is_file():
            raise NotFoundError(f"Policy '{stem}' not found")
        content = path.read_text(encoding="utf-8")
        return PolicyDTO(stem, _title_from(content, stem), content)
