"""Minimal storage boundary, retained for forward-compatible implementations."""

from abc import ABC, abstractmethod

from app.contracts import AuditEvent


class AuditStore(ABC):
    @abstractmethod
    def record_event(self, event: AuditEvent) -> None:
        """Persist an event without leaking sensitive payload values."""
