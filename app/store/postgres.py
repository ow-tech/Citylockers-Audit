"""PostgreSQL storage placeholder.

The schema is established before ingestion is implemented.
"""

from app.contracts import AuditEvent
from app.store.base import AuditStore


class PostgresAuditStore(AuditStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def record_event(self, event: AuditEvent) -> None:
        raise NotImplementedError("PostgreSQL event ingestion is not implemented yet")
