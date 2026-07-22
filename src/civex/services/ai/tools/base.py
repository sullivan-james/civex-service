"""AiTool ABC + AiToolContext -- the tool registry's equivalent of
plugins/base.py's Tier0Plugin/WorkflowContext, for AI-assistant tools.

A tool's run() body should read like a CLI command: unpack tool_input, call
one or a few service methods, shape the result. Nothing else -- see CLAUDE.md
"AI tools are a third thin entry point" in the CIVEX-41 epic plan.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from civex.context import AppContext
    from civex.services.dataset_service import DatasetService
    from civex.services.plugin_service import PluginService
    from civex.services.record_service import RecordService
    from civex.services.schema_service import SchemaService
    from civex.services.workflow_job_service import WorkflowJobService
    from civex.services.workflow_service import WorkflowService


@dataclass
class AiToolContext:
    schema_svc: SchemaService
    dataset_svc: DatasetService
    record_svc: RecordService
    job_svc: WorkflowJobService
    workflow_svc: WorkflowService
    plugin_svc: PluginService
    _app_ctx: AppContext  # escape hatch: validation_scope() needs the session

    @contextmanager
    def validation_scope(self) -> Iterator[None]:
        with self._app_ctx.validation_scope():
            yield


class AiTool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    mutating: bool = False

    @abstractmethod
    def run(self, tool_input: dict[str, Any], ctx: AiToolContext) -> Any:
        """Return a JSON-serializable value (dispatch() will json.dumps() it),
        or a str to pass through unchanged (act tools already build their own
        JSON-encoded proposal/error strings; get_workflow_authoring_guide
        returns raw markdown, not JSON, by design)."""
        ...
