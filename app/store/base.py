from abc import ABC, abstractmethod
from typing import Literal

from app.contracts import AuditEvent, SourceCheckpoint

RecordResult = Literal["accepted", "duplicate"]


class AuditStore(ABC):
    @abstractmethod
    def record_event(self, event: AuditEvent) -> RecordResult: ...

    @abstractmethod
    def query_events(self, *, source_system: str | None = None, source_stream: str | None = None, source_record_id: str | None = None) -> list[AuditEvent]: ...

    @abstractmethod
    def all_events(self) -> list[AuditEvent]: ...

    @abstractmethod
    def save_checkpoint(self, checkpoint: SourceCheckpoint) -> SourceCheckpoint: ...

    @abstractmethod
    def get_checkpoint(self, source_name: str) -> SourceCheckpoint | None: ...
