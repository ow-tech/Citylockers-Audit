import os
from datetime import datetime
from uuid import uuid4

import pytest

from app.khizana_collector import (
    CHECKPOINT_TYPE,
    KhizanaAuthoritativeCollector,
    KhizanaCollectorConfig,
    SUPPORTED_SOURCES,
    configured_collector,
    event_from_export,
)
from app.store.memory import MemoryAuditStore


DATABASE_URL = os.environ.get("AUDIT_TEST_DATABASE_URL")


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


class FakeExport:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def get(self, _url, *, headers, params, timeout):
        self.requests.append((headers, params, timeout))
        source = params["source"]
        cursor = (params.get("after_occurred_at"), params.get("after_record_id"))
        return FakeResponse({"events": self.pages.get((source, cursor), [])})


def exported(record_id: str, occurred_at: str, *, surface: bool = False):
    return {
        "source_system": "KH",
        "source_stream": "booking.bookings",
        "source_record_id": record_id,
        "source_transition": "created",
        "source_occurred_at": occurred_at,
        "event_type": "booking.created",
        "result": "success",
        "booking_id": f"booking-{record_id}",
        "booking_reference": f"REF-{record_id}",
        "attributes": {"source_surface": "citylockers_site"} if surface else {},
    }


def collector(store, client):
    return KhizanaAuthoritativeCollector(
        KhizanaCollectorConfig("http://khizana.local/functions/v1/audit-authoritative-activity-export", "export-token", page_size=2),
        store,
        client,
    )


def test_collector_advances_composite_cursor_without_skipping_same_timestamp_rows_and_restarts() -> None:
    at = "2026-10-03T08:00:00+00:00"
    later = "2026-10-03T08:00:01+00:00"
    pages = {
        ("booking.bookings", (None, None)): [exported("a", at, surface=True), exported("b", at)],
        ("booking.bookings", (at, "b")): [exported("c", later)],
    }
    client, store = FakeExport(pages), MemoryAuditStore()
    first = collector(store, client)
    assert first.poll_source("booking.bookings") == 3
    checkpoint = store.get_checkpoint("khizana:booking.bookings")
    assert checkpoint is not None
    assert checkpoint.cursor_type == CHECKPOINT_TYPE
    assert checkpoint.cursor_value == datetime.fromisoformat(later).isoformat()
    assert checkpoint.metadata == {"record_id": "c"}
    assert len(store.all_events()) == 3
    assert store.all_events()[0].metadata.source_surface == "citylockers_site"

    restarted = collector(store, client)
    assert restarted.poll_source("booking.bookings") == 0
    assert len(store.all_events()) == 3
    assert client.requests[-1][1]["after_record_id"] == "c"


def test_collector_retry_is_idempotent_when_checkpoint_write_is_interrupted() -> None:
    store = MemoryAuditStore()
    client = FakeExport({("booking.bookings", (None, None)): [exported("a", "2026-10-03T08:00:00+00:00")]})
    active = collector(store, client)
    original_save = store.save_checkpoint

    def fail_once(_checkpoint):
        store.save_checkpoint = original_save
        raise RuntimeError("central checkpoint database unavailable")

    store.save_checkpoint = fail_once
    with pytest.raises(RuntimeError):
        active.poll_source("booking.bookings")
    assert len(store.all_events()) == 1
    assert active.poll_source("booking.bookings") == 1
    assert len(store.all_events()) == 1


def test_collector_rejects_unapproved_metadata_and_never_copies_provider_fields() -> None:
    raw = exported("a", "2026-10-03T08:00:00+00:00")
    raw["provider_evidence"] = "not transported"
    raw["attributes"] = {"card_last4": "1234"}
    event = event_from_export("booking.bookings", raw)
    assert event.metadata.model_dump(exclude_none=True) == {
        "booking_id": "booking-a", "booking_reference": "REF-a", "result": "success",
    }


def test_collector_configuration_is_explicitly_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("KHIZANA_AUDIT_COLLECTOR_ENABLED", raising=False)
    assert configured_collector() is None
    monkeypatch.setenv("KHIZANA_AUDIT_COLLECTOR_ENABLED", "true")
    with pytest.raises(ValueError, match="requires"):
        configured_collector()


def test_collector_supports_only_approved_durable_streams() -> None:
    assert set(SUPPORTED_SOURCES) == {
        "booking.bookings", "booking.transactions", "finance.refund_requests",
        "booking.terminal_void_operations", "booking.terminal_payment_attempts",
        "booking.bridge_switch_operations", "booking.device_installs",
        "partner.bridge_requests", "booking.manual_refund_marks",
    }


def test_one_source_failure_does_not_starve_other_sources() -> None:
    class OneSourceFails(FakeExport):
        def get(self, _url, *, headers, params, timeout):
            self.requests.append((headers, params, timeout))
            if params["source"] == "booking.bookings":
                raise RuntimeError("export unavailable")
            return FakeResponse({"events": []})

    client = OneSourceFails({})
    with pytest.raises(RuntimeError, match="export unavailable"):
        collector(MemoryAuditStore(), client).poll_once()
    assert {request[1]["source"] for request in client.requests} == set(SUPPORTED_SOURCES)


@pytest.mark.skipif(not DATABASE_URL, reason="AUDIT_TEST_DATABASE_URL is required for PostgreSQL collector proof")
def test_collector_persists_idempotently_to_central_postgres_and_resumes() -> None:
    from psycopg import connect

    from app.store.postgres import PostgresAuditStore

    with connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO audit.systems (code, name) VALUES ('KH', 'Khizana') ON CONFLICT (code) DO NOTHING")
        cursor.execute("DELETE FROM audit.source_checkpoints WHERE source_name = 'khizana:booking.bookings'")
    at, later = "2026-10-03T08:00:00+00:00", "2026-10-03T08:00:01+00:00"
    suffix = str(uuid4())
    pages = {
        ("booking.bookings", (None, None)): [exported(f"{suffix}-a", at, surface=True), exported(f"{suffix}-b", at)],
        ("booking.bookings", (at, f"{suffix}-b")): [exported(f"{suffix}-c", later)],
    }
    store, client = PostgresAuditStore(DATABASE_URL), FakeExport(pages)
    assert collector(store, client).poll_source("booking.bookings") == 3
    assert len(store.query_events(source_system="KH", source_stream="booking.bookings", source_record_id=f"{suffix}-a")) == 1
    assert collector(store, client).poll_source("booking.bookings") == 0
    checkpoint = store.get_checkpoint("khizana:booking.bookings")
    assert checkpoint is not None and checkpoint.metadata == {"record_id": f"{suffix}-c"}
