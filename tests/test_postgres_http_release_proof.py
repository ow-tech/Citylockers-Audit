import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.contracts import AuditEvent, SourceCheckpoint
from app.store.postgres import PostgresAuditStore


DATABASE_URL = os.environ.get("AUDIT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="AUDIT_TEST_DATABASE_URL is required for PostgreSQL integration tests")


def ids() -> tuple[str, str, str]:
    return str(uuid4()), str(uuid4()), str(uuid4())


def postgres_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, str], dict[str, str]]:
    monkeypatch.setenv("AUDIT_INGEST_TOKEN", "postgres-ingest-token")
    monkeypatch.setenv("AUDIT_QUERY_TOKEN", "postgres-query-token")
    monkeypatch.setattr(main, "store", PostgresAuditStore(DATABASE_URL))
    return TestClient(main.app), {"Authorization": "Bearer postgres-ingest-token"}, {"Authorization": "Bearer postgres-query-token"}


def test_postgres_events_provenance_idempotency_and_checkpoints() -> None:
    store = PostgresAuditStore(DATABASE_URL)
    occurred_at = datetime.now(timezone.utc)
    source_id = f"booking-{uuid4()}"
    created = AuditEvent(system_code="KH", event_type="booking.created", occurred_at=occurred_at,
                         source_kind="business_activity", source_system="KH", source_stream="booking.bookings",
                         source_record_id=source_id, source_transition="created", source_occurred_at=occurred_at)
    assert store.record_event(created) == "accepted"
    assert store.record_event(created) == "duplicate"
    assert store.record_event(created.model_copy(update={"event_id": str(uuid4())})) == "duplicate"
    completed = created.model_copy(update={"event_id": str(uuid4()), "source_transition": "completed"})
    assert store.record_event(completed) == "accepted"
    rows = store.query_events(source_system="KH", source_stream="booking.bookings", source_record_id=source_id)
    assert {(row.source_transition, row.source_occurred_at) for row in rows} == {("created", occurred_at), ("completed", occurred_at)}

    source_name = f"khizana-{uuid4()}"
    first = store.save_checkpoint(SourceCheckpoint(source_name=source_name, cursor_value="10", cursor_type="id"))
    assert store.get_checkpoint(source_name) == first
    updated = store.save_checkpoint(SourceCheckpoint(source_name=source_name, cursor_value="11", cursor_type="id"))
    assert updated.cursor_value == "11"
    assert store.get_checkpoint(source_name) == updated


def test_postgres_http_cl_pa_ks_trace_and_keyset_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    api, ingest, query = postgres_client(monkeypatch)
    trace_id, operation_id, request_id = ids()
    occurred_at = datetime.now(timezone.utc).replace(microsecond=0)

    cl_id, pa_id, ks_id = str(uuid4()), str(uuid4()), str(uuid4())
    cl = {"event_id": cl_id, "system_code": "CL", "event_type": "client.error", "occurred_at": occurred_at.isoformat(),
          "trace_id": trace_id, "request_id": request_id, "source_kind": "explicit_error",
          "metadata": {"error_code": "CL-APP-001", "reference": "CL-RP-001", "fingerprint": "cl-proof-fp", "booking_id": "booking-proof"}}
    pa = {"event_id": pa_id, "system_code": "PA", "event_type": "partner.api.error", "occurred_at": (occurred_at + timedelta(seconds=1)).isoformat(),
          "trace_id": trace_id, "operation_id": operation_id, "request_id": request_id, "source_kind": "explicit_error",
          "metadata": {"error_code": "PA-AUTH-001", "reference": "PA-RP-001", "fingerprint": "pa-proof-fp", "payment_status": "failed"}}
    ks = {"event_id": ks_id, "system_code": "KS", "event_type": "locker.unlock_actuation_sent", "occurred_at": (occurred_at + timedelta(seconds=2)).isoformat(),
          "trace_id": trace_id, "operation_id": operation_id, "request_id": request_id, "source_kind": "operational_event",
          "source_system": "KS", "source_stream": "gateway.actuations", "source_record_id": f"actuation-{uuid4()}", "source_transition": "sent",
          "source_occurred_at": (occurred_at + timedelta(seconds=2)).isoformat(),
          "metadata": {"device_id": "device-proof", "wall_id": "wall-proof", "locker_id": "locker-proof", "result": "sent"}}
    for payload in (cl, pa, ks):
        assert api.post("/v1/events", json=payload, headers=ingest).status_code == 200

    for needle, event_id in (("CL-APP-001", cl_id), ("CL-RP-001", cl_id), (trace_id, cl_id), ("PA-AUTH-001", pa_id), ("PA-RP-001", pa_id)):
        result = api.get("/v1/events", params={"search": needle, "from_at": (occurred_at - timedelta(seconds=1)).isoformat(), "to_at": (occurred_at + timedelta(seconds=3)).isoformat()}, headers=query)
        assert result.status_code == 200
        assert any(item["event_id"] == event_id for item in result.json()["items"])
    pa_result = api.get("/v1/errors", params={"error_code": "PA-AUTH-001", "from_at": (occurred_at - timedelta(seconds=1)).isoformat(), "to_at": (occurred_at + timedelta(seconds=3)).isoformat()}, headers=query).json()["items"]
    assert any(item["reference"] == "PA-RP-001" and "payment_status" in item["attributes"] for item in pa_result)
    assert api.get("/v1/error-definitions/PA-AUTH-001", headers=query).json()["code"] == "PA-AUTH-001"
    detail = api.get(f"/v1/errors/{pa_id}", headers=query).json()
    assert detail["reference"] == "PA-RP-001"
    assert detail["recurrence"]["occurrences"] >= 1
    assert "postgres-ingest-token" not in str(pa_result)
    assert "postgres-query-token" not in str(pa_result)

    timeline = api.get(f"/v1/traces/{trace_id}", headers=query).json()["items"]
    proof_items = [item for item in timeline if item["event_id"] in {cl_id, pa_id, ks_id}]
    assert [item["event_id"] for item in proof_items] == [cl_id, pa_id, ks_id]
    ks_item = proof_items[-1]
    assert ks_item["event_type"] == "locker.unlock_actuation_sent"
    assert ks_item["source_system"] == "KS"
    assert ks_item["source_stream"] == "gateway.actuations"
    assert ks_item["operation_id"] == operation_id and ks_item["request_id"] == request_id
    assert "locker.opened" not in str(ks_item)
    source_result = api.get("/v1/events", params={"source_system": "KS", "from_at": (occurred_at - timedelta(seconds=1)).isoformat(), "to_at": (occurred_at + timedelta(seconds=3)).isoformat()}, headers=query).json()["items"]
    assert any(item["event_id"] == ks_id for item in source_result)

    same_timestamp_ids = [str(uuid4()), str(uuid4()), str(uuid4())]
    for event_id in same_timestamp_ids:
        assert api.post("/v1/events", json={"event_id": event_id, "system_code": "CL", "event_type": "page.proof", "occurred_at": occurred_at.isoformat(), "source_kind": "explicit_event"}, headers=ingest).status_code == 200
    page_params = {"event_type": "page.proof", "from_at": (occurred_at - timedelta(seconds=1)).isoformat(), "to_at": (occurred_at + timedelta(seconds=3)).isoformat(), "limit": 1}
    first_page = api.get("/v1/events", params=page_params, headers=query).json()
    second_page = api.get("/v1/events", params={**page_params, "cursor": first_page["next_cursor"]}, headers=query).json()
    third_page = api.get("/v1/events", params={**page_params, "cursor": second_page["next_cursor"]}, headers=query).json()
    page_ids = [item["event_id"] for item in first_page["items"] + second_page["items"] + third_page["items"]]
    assert set(page_ids) == set(same_timestamp_ids)
    assert len(page_ids) == len(set(page_ids))
