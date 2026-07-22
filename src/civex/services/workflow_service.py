"""Workflow YAML file management: list, read, validate, save, delete.

Single source of truth for workflow file I/O -- previously duplicated
independently in server/routers/workflows.py and the AI list_workflows/
save_workflow tools (CIVEX-54).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from civex.domain.exceptions import NotFoundError, ValidationError
from civex.workflows.contract_validation import validate_workflow_contracts
from civex.workflows.definition import WorkflowDef, load_workflow

if TYPE_CHECKING:
    from civex.plugins.registry import PluginRegistration

_SAFE_STEM = re.compile(r"^[\w-]+$")

PluginsProvider = Callable[[], Mapping[str, "PluginRegistration"]]


class WorkflowService:
    def __init__(self, civex_dir: Path, plugins_provider: PluginsProvider) -> None:
        """`plugins_provider` is called per validation rather than held as a
        snapshot: a plugin edited (or added) since this service was built has
        to be visible to the next save, which is what makes CIVEX-142's
        revalidation lazy. It's cheap to call -- discovery re-describes only
        plugin files whose contents actually changed."""
        self._dir = civex_dir / "workflows"
        self._plugins_provider = plugins_provider

    def list_defs(self) -> list[tuple[Path, WorkflowDef]]:
        """Every parseable workflow file as (path, parsed def). Files that
        fail to parse are silently skipped -- matches the pre-existing
        behavior of the router's workflow list/run lookups."""
        if not self._dir.exists():
            return []
        results = []
        for path in sorted(self._dir.glob("*.yaml")) + sorted(self._dir.glob("*.yml")):
            try:
                results.append((path, load_workflow(path)))
            except Exception:
                continue
        return results

    def find_by_name(self, name: str) -> WorkflowDef | None:
        """Match by workflow name or filename stem."""
        for path, wf in self.list_defs():
            if wf.name == name or path.stem == name:
                return wf
        return None

    def find_path(self, stem: str) -> Path | None:
        for ext in ("yaml", "yml"):
            p = self._dir / f"{stem}.{ext}"
            if p.exists():
                return p
        return None

    def get(self, stem: str) -> tuple[Path, WorkflowDef, str]:
        """Raw content + parsed def for one workflow.

        Raises NotFoundError if the stem doesn't exist, ValidationError if
        the YAML doesn't parse.
        """
        path = self.find_path(stem)
        if path is None:
            raise NotFoundError(f"Workflow '{stem}' not found")
        content = path.read_text(encoding="utf-8")
        try:
            wf = load_workflow(path)
        except Exception as e:
            raise ValidationError(f"Invalid workflow YAML: {e}")
        return path, wf, content

    def list_raw(self) -> list[dict]:
        """[{"filename", "content"}] for every *.yaml file, or {"filename",
        "error"} for one that fails to read -- for the AI list_workflows
        tool, which wants full source text rather than parsed metadata."""
        if not self._dir.exists():
            return []
        results = []
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                results.append(
                    {"filename": path.name, "content": path.read_text(encoding="utf-8")}
                )
            except Exception as e:
                results.append({"filename": path.name, "error": str(e)})
        return results

    def validate(self, stem: str, content: str) -> WorkflowDef:
        """Check stem format, YAML validity, and every step against the
        contract its plugin declared, without writing anything.

        Contract violations are reported together rather than one at a time
        -- whoever is fixing them (often the AI's save_workflow tool) would
        otherwise have to resubmit once per error.

        Raises ValidationError on failure.
        """
        if not _SAFE_STEM.match(stem):
            raise ValidationError(
                "stem must contain only letters, numbers, hyphens, and underscores"
            )
        try:
            raw = yaml.safe_load(content)
            wf = WorkflowDef.model_validate(raw)
        except Exception as e:
            raise ValidationError(f"Invalid workflow YAML: {e}")

        errors = validate_workflow_contracts(wf, self._plugins_provider())
        if errors:
            raise ValidationError("\n".join(errors))
        return wf

    def save(self, stem: str, content: str) -> tuple[Path, WorkflowDef]:
        wf = self.validate(stem, content)
        path = self._dir / f"{stem}.yaml"
        path.write_text(content, encoding="utf-8")
        return path, wf

    def delete(self, stem: str) -> None:
        path = self.find_path(stem)
        if path is None:
            raise NotFoundError(f"Workflow '{stem}' not found")
        path.unlink()
