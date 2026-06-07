from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel

from civex.domain.dtos import DatasetDTO, RecordDTO

if TYPE_CHECKING:
    from civex.context import AppContext


class BasePlugin(ABC):
    id: str
    name: str
    category: str = "general"

    class Config(BaseModel):
        pass

    @abstractmethod
    def run(
        self,
        inputs: dict[str, Any],
        config: "BasePlugin.Config",
        ctx: "WorkflowContext",
    ) -> dict[str, Any]: ...


@dataclass
class WorkflowContext:
    record: RecordDTO
    dataset: DatasetDTO
    _app_ctx: "AppContext"

    def get_file(self, sha256: str) -> bytes:
        return self._app_ctx.file_svc.retrieve(sha256)

    def update_record(self, data: dict[str, Any]) -> None:
        self._app_ctx.record_svc.update(str(self.record.id), data)

    def create_record(
        self,
        dataset_name: str,
        schema_name: str,
        data: dict[str, Any],
        parent_record_id: str | None = None,
    ) -> RecordDTO:
        return self._app_ctx.record_svc.add(dataset_name, schema_name, data, parent_record_id=parent_record_id)

    def commit(self) -> None:
        self._app_ctx.commit()
