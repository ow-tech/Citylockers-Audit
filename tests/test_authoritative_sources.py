from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.contracts import AuditEvent, SourceCheckpoint, deterministic_adapter_event_id
from app.main import app, store
from app.store.memory import MemoryAuditStore


def source_event(transition="created", event_id=None):
    return AuditEvent(event_id=event_id, system_code="KH", event_type="booking.created", occurred_at=datetime(2026, 9, 29, tzinfo=timezone.utc), source_kind="business_activity", source_system="KH", source_stream="booking.bookings", source_record_id="booking-1", source_transition=transition)


def test_deterministic_adapter_id_and_transition() -> None:
    assert deterministic_adapter_event_id("KH", "booking.bookings", "booking-1", "created") == source_event().event_id
    assert source_event().event_id != source_event("completed").event_id


def test_memory_deduplicates_event_id_and_source_identity() -> None:
    audit_store = MemoryAuditStore()
    assert audit_store.record_event(source_event()) == "accepted"
    assert audit_store.record_event(source_event()) == "duplicate"
    assert audit_store.record_event(source_event(event_id="changed-id")) == "duplicate"


def test_explicit_event_without_source_is_accepted() -> None:
    event = AuditEvent(system_code="BR", event_type="bridge.error", occurred_at=datetime.now(timezone.utc), source_kind="explicit_error")
    assert MemoryAuditStore().record_event(event) == "accepted"


def test_checkpoint_create_update_read() -> None:
    audit_store = MemoryAuditStore()
    audit_store.save_checkpoint(SourceCheckpoint(source_name="khizana", cursor_value="10", cursor_type="id"))
    updated = audit_store.save_checkpoint(SourceCheckpoint(source_name="khizana", cursor_value="11", cursor_type="id"))
    assert audit_store.get_checkpoint("khizana") == updated


def test_batch_returns_mixed_counts_without_echoing_bad_payload() -> None:
    store.events.clear(); store._source_events.clear()
    payload = source_event().model_dump(mode="json")
    response = TestClient(app).post("/v1/events/batch", json=[payload, payload, {"secret": "not-returned"}])
    assert response.json() == {"accepted": 1, "duplicate": 1, "rejected": 1, "rejections": [{"index": 2, "code": "invalid_event"}]}


def test_migration_has_source_guard_and_checkpoints() -> None:
    migration = open("storage/migrations/001_init.sql").read()
    assert "NULLS NOT DISTINCT" in migration
    assert "audit.source_checkpoints" in migration
