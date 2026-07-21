from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from civex.domain.dtos import DatasetDTO, RecordDTO
from civex_plugin_sdk.plugin_base import PluginBase

if TYPE_CHECKING:
    from civex.context import AppContext


class BasePlugin(ABC):
    """Legacy in-process plugin contract, kept unchanged for backward
    compatibility with existing user files under `_civex/plugins/*.py`.
    New built-in plugins implement Tier0Plugin instead (see CIVEX-126)."""

    id: str
    name: str
    category: str = "general"

    class Config(BaseModel):
        pass

    @abstractmethod
    def run(
        self,
        inputs: dict[str, Any],
        config: Any,
        ctx: "WorkflowContext",
    ) -> dict[str, Any]: ...


class PluginTier(str, Enum):
    """Which runtime executes a plugin. Only BUILTIN is populated today —
    SUBPROCESS/CONTAINER are structurally reserved for CIVEX-127+ so the
    registry doesn't need another redesign when those tiers land."""

    BUILTIN = "builtin"
    SUBPROCESS = "subprocess"
    CONTAINER = "container"


@dataclass
class StepResult:
    """Uniform return shape for PluginRegistration.invoke(), regardless of
    tier. `logs`/`error` are unused by tier BUILTIN this story (exceptions
    still propagate and are logged by the executor exactly as before) — they
    exist so subprocess/container tiers have somewhere to put out-of-band
    log lines / structured RPC error envelopes without another interface
    change."""

    outputs: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: Any | None = None


class Tier0Plugin(PluginBase, ABC):
    """New-style in-process plugin contract that all built-in plugins
    implement. Shares its id/name/category/capabilities/Config declarations
    with civex-plugin-sdk's out-of-process `Plugin` (via the common
    `PluginBase`) so that shape can't drift between tiers -- only `invoke()`
    itself is declared separately per tier, since the in-process
    WorkflowContext and out-of-process Ctx deliberately expose different
    surfaces (WorkflowContext gives ambient `.record`/`.dataset` access that
    Ctx intentionally withholds from untrusted out-of-process code; several
    built-ins rely on that ambient access, e.g. get_field/save_field/
    extract_from_filename).

    Capability declarations are metadata only here — not enforced for tier
    BUILTIN, since capability allowlisting is an RPC-boundary control for
    untrusted out-of-process tiers, and there's no RPC call to intercept for
    in-process execution."""

    @abstractmethod
    def invoke(
        self,
        inputs: dict[str, Any],
        config: Any,
        ctx: "WorkflowContext",
    ) -> dict[str, Any]: ...


@dataclass
class WorkflowContext:
    record: RecordDTO
    dataset: DatasetDTO
    _app_ctx: "AppContext"
    job_depth: int = 0

    def get_file(self, sha256: str) -> bytes:
        return self._app_ctx.file_svc.retrieve(sha256)

    def update_record(self, data: dict[str, Any]) -> None:
        self._app_ctx.record_svc.update(
            str(self.record.id), data, _job_depth=self.job_depth + 1
        )

    def create_record(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        parent_record_id: str | None = None,
    ) -> RecordDTO:
        return self._app_ctx.record_svc.add(
            dataset_name,
            schema_name,
            data,
            parent_record_id=parent_record_id,
            _job_depth=self.job_depth + 1,
        )

    def commit(self) -> None:
        self._app_ctx.commit()
