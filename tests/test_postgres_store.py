import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import connect

from app import main
from app.contracts import AuditEvent, SourceCheckpoint
from app.store.postgres import PostgresAuditStore


DATABASE_URL = os.environ.get("AUDIT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AUDIT_TEST_DATABASE_URL is required for PostgreSQL integration tests")


def source_event(*, record_id: str = "booking-1", transition: str = "created", event_id: str | None = None) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        system_code="KH",
        event_type="booking.created",
        occurred_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        source_kind="business_activity",
        source_system="KH",
        source_stream="booking.bookings",
        source_record_id=record_id,
        source_transition=transition,
        source_occurred_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
    )


def test_postgres_store_enforces_source_provenance_and_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIT_INGEST_TOKEN", "test-ingest-token")
    store = PostgresAuditStore(DATABASE_URL)
    with connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO audit.systems (code, name) VALUES ('KH', 'Khizana'), ('BR', 'Bridge') ON CONFLICT (code) DO NOTHING")

    record_id = f"booking-{uuid4()}"
    first = source_event(record_id=record_id)
    assert store.record_event(first) == "accepted"
    assert store.record_event(first) == "duplicate"
    assert store.record_event(source_event(record_id=record_id, event_id=str(uuid4()))) == "duplicate"
    assert store.record_event(source_event(record_id=record_id, transition="completed")) == "accepted"
    assert store.record_event(AuditEvent(system_code="BR", event_type="bridge.error", occurred_at=datetime.now(timezone.utc), source_kind="explicit_error",
                                         metadata={"error_code": "BR-UNCA-001", "reference": "BR-SR-test-001"})) == "accepted"

    created = store.save_checkpoint(SourceCheckpoint(source_name="khizana", cursor_value="10", cursor_type="id"))
    updated = store.save_checkpoint(SourceCheckpoint(source_name="khizana", cursor_value="11", cursor_type="id"))
    assert created.cursor_value == "10"
    assert updated.cursor_value == "11"
    assert store.get_checkpoint("khizana") == updated
    assert {event.event_id for event in store.query_events(source_system="KH", source_stream="booking.bookings", source_record_id=record_id)} == {first.event_id, source_event(record_id=record_id, transition="completed").event_id}

    monkeypatch.setattr(main, "store", store)
    batch_event = source_event(record_id=f"booking-{uuid4()}").model_dump(mode="json")
    response = TestClient(main.app).post("/v1/events/batch", json=[batch_event, batch_event], headers={"Authorization": "Bearer test-ingest-token"})
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "duplicate": 1, "rejected": 0, "rejections": []}
