from app.contracts import AuditEvent, SourceCheckpoint
from app.store.base import AuditStore, RecordResult


class MemoryAuditStore(AuditStore):
    def __init__(self) -> None:
        self.events: dict[str, AuditEvent] = {}
        self._source_events: dict[tuple[str, str, str, str | None], str] = {}
        self._checkpoints: dict[str, SourceCheckpoint] = {}

    def record_event(self, event: AuditEvent) -> RecordResult:
        if event.event_id in self.events or event.source_identity in self._source_events:
            return "duplicate"
        self.events[event.event_id] = event
        if event.source_identity is not None:
            self._source_events[event.source_identity] = event.event_id
        return "accepted"

    def query_events(self, *, source_system: str | None = None, source_stream: str | None = None, source_record_id: str | None = None) -> list[AuditEvent]:
        return [event for event in self.events.values() if (source_system is None or event.source_system == source_system) and (source_stream is None or event.source_stream == source_stream) and (source_record_id is None or event.source_record_id == source_record_id)]

    def save_checkpoint(self, checkpoint: SourceCheckpoint) -> SourceCheckpoint:
        self._checkpoints[checkpoint.source_name] = checkpoint
        return checkpoint

    def get_checkpoint(self, source_name: str) -> SourceCheckpoint | None:
        return self._checkpoints.get(source_name)
