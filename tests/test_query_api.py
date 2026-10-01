from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.contracts import AuditEvent
from app.main import app, store


def error(event_id: str, occurred_at: datetime, *, reference: str = "PA-ABC123") -> AuditEvent:
    return AuditEvent(event_id=event_id, system_code="PA", event_type="partner.api.error", occurred_at=occurred_at,
                      trace_id="trace-1", request_id="request-1", source_kind="explicit_error",
                      metadata={"error_code": "PA-AUTH-001", "reference": reference, "fingerprint": "fp-1",
                                "booking_id": "booking-1", "authorization": "must-not-leak"})


def client(monkeypatch):
    monkeypatch.setenv("AUDIT_QUERY_TOKEN", "read-only-test-token")
    store.events.clear(); store._source_events.clear()
    return TestClient(app), {"Authorization": "Bearer read-only-test-token"}


def test_read_api_requires_distinct_query_token(monkeypatch) -> None:
    api, headers = client(monkeypatch)
    assert api.get("/v1/errors").status_code == 401
    assert api.get("/v1/errors", headers={"Authorization": "Bearer ingest-token"}).status_code == 401
    assert api.get("/v1/errors", headers=headers).status_code == 200
    assert api.post("/v1/events", json={"system_code": "CL", "event_type": "client.error", "occurred_at": "2026-10-01T00:00:00Z"}, headers=headers).status_code == 401


def test_errors_are_filterable_paginated_and_sanitized(monkeypatch) -> None:
    api, headers = client(monkeypatch)
    first = error("00000000-0000-0000-0000-000000000001", datetime(2026, 10, 1, tzinfo=timezone.utc))
    second = error("00000000-0000-0000-0000-000000000002", datetime(2026, 10, 1, tzinfo=timezone.utc), reference="PA-DEF456")
    store.record_event(first); store.record_event(second)
    response = api.get("/v1/errors", params={"search": "PA-DEF456", "limit": 1}, headers=headers)
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["reference"] == "PA-DEF456"
    assert "authorization" not in item["attributes"]
    assert api.get("/v1/errors", params={"limit": 101}, headers=headers).status_code == 422
    assert api.get("/v1/errors", params={"from_at": "2026-01-01T00:00:00Z", "to_at": "2026-03-15T00:00:00Z"}, headers=headers).status_code == 422
    assert api.get("/v1/traces/trace-1", headers=headers).json()["items"]


def test_error_detail_definition_and_recurrence(monkeypatch) -> None:
    api, headers = client(monkeypatch)
    occurrence = error("00000000-0000-0000-0000-000000000003", datetime.now(timezone.utc))
    store.record_event(occurrence)
    response = api.get(f"/v1/errors/{occurrence.event_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["definition"]["code"] == "PA-AUTH-001"
    assert response.json()["recurrence"]["occurrences"] == 1
