"""PostgreSQL storage with database-enforced idempotency."""

from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.contracts import AuditEvent, SourceCheckpoint
from app.store.base import AuditStore, RecordResult


class PostgresAuditStore(AuditStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def record_event(self, event: AuditEvent) -> RecordResult:
        with connect(self.database_url) as connection, connection.cursor() as cursor:
            if event.trace_id:
                cursor.execute(
                    """INSERT INTO audit.traces (trace_id, operation_id) VALUES (%s, %s)
                       ON CONFLICT (trace_id) DO UPDATE SET operation_id = COALESCE(audit.traces.operation_id, EXCLUDED.operation_id)""",
                    (event.trace_id, event.operation_id),
                )
            cursor.execute(
                """INSERT INTO audit.audit_events (event_id, system_code, event_type, occurred_at, trace_id, operation_id, request_id, metadata, source_kind, source_system, source_stream, source_record_id, source_transition, source_occurred_at)
                   VALUES (%(event_id)s, %(system_code)s, %(event_type)s, %(occurred_at)s, %(trace_id)s, %(operation_id)s, %(request_id)s, %(metadata)s, %(source_kind)s, %(source_system)s, %(source_stream)s, %(source_record_id)s, %(source_transition)s, %(source_occurred_at)s)
                   ON CONFLICT DO NOTHING RETURNING event_id""",
                {**event.model_dump(mode="json"), "metadata": Jsonb(event.metadata)},
            )
            return "accepted" if cursor.fetchone() else "duplicate"

    def query_events(self, *, source_system: str | None = None, source_stream: str | None = None, source_record_id: str | None = None) -> list[AuditEvent]:
        clauses, values = [], []
        for column, value in (("source_system", source_system), ("source_stream", source_stream), ("source_record_id", source_record_id)):
            if value is not None:
                clauses.append(f"{column} = %s")
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        fields = "event_id::text AS event_id, system_code, event_type, occurred_at, trace_id::text AS trace_id, operation_id::text AS operation_id, request_id, metadata, source_kind, source_system, source_stream, source_record_id, source_transition, source_occurred_at"
        with connect(self.database_url, row_factory=dict_row) as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT {fields} FROM audit.audit_events{where} ORDER BY occurred_at", values)
            return [AuditEvent.model_validate(row) for row in cursor.fetchall()]

    def all_events(self) -> list[AuditEvent]:
        fields = "event_id::text AS event_id, system_code, event_type, occurred_at, trace_id::text AS trace_id, operation_id::text AS operation_id, request_id, metadata, source_kind, source_system, source_stream, source_record_id, source_transition, source_occurred_at"
        with connect(self.database_url, row_factory=dict_row) as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT {fields} FROM audit.audit_events")
            return [AuditEvent.model_validate(row) for row in cursor.fetchall()]

    def save_checkpoint(self, checkpoint: SourceCheckpoint) -> SourceCheckpoint:
        with connect(self.database_url, row_factory=dict_row) as connection, connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO audit.source_checkpoints (source_name, cursor_value, cursor_type, updated_at, metadata)
                   VALUES (%(source_name)s, %(cursor_value)s, %(cursor_type)s, %(updated_at)s, %(metadata)s)
                   ON CONFLICT (source_name) DO UPDATE SET cursor_value = EXCLUDED.cursor_value, cursor_type = EXCLUDED.cursor_type, updated_at = EXCLUDED.updated_at, metadata = EXCLUDED.metadata
                   RETURNING source_name, cursor_value, cursor_type, updated_at, metadata""",
                {**checkpoint.model_dump(mode="json"), "metadata": Jsonb(checkpoint.metadata)},
            )
            return SourceCheckpoint.model_validate(cursor.fetchone())

    def get_checkpoint(self, source_name: str) -> SourceCheckpoint | None:
        with connect(self.database_url, row_factory=dict_row) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT source_name, cursor_value, cursor_type, updated_at, metadata FROM audit.source_checkpoints WHERE source_name = %s", (source_name,))
            row = cursor.fetchone()
            return SourceCheckpoint.model_validate(row) if row else None
