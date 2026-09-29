"""Development-only in-memory store."""

from app.contracts import AuditEvent
from app.store.base import AuditStore


class MemoryAuditStore(AuditStore):
    def __init__(self) -> None:
        self.events: dict[str, AuditEvent] = {}

    def record_event(self, event: AuditEvent) -> None:
        self.events.setdefault(event.event_id, event)
