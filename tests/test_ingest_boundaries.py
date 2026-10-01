import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app import main
from app.main import MAX_BODY_BYTES
from app.store.memory import MemoryAuditStore


def event(metadata: dict | None = None) -> dict:
    return {
        "system_code": "CL",
        "event_type": "client.error",
        "occurred_at": "2026-10-01T00:00:00Z",
        "metadata": metadata or {"payment_status": "failed"},
    }


def client(monkeypatch):
    monkeypatch.setenv("AUDIT_INGEST_TOKEN", "ingest-only-token")
    monkeypatch.setenv("AUDIT_QUERY_TOKEN", "query-only-token")
    monkeypatch.setattr(main, "store", MemoryAuditStore())
    return TestClient(main.app)


def test_http_tokens_are_strictly_scoped(monkeypatch) -> None:
    api = client(monkeypatch)
    ingest = {"Authorization": "Bearer ingest-only-token"}
    query = {"Authorization": "Bearer query-only-token"}
    assert api.post("/v1/events", json=event(), headers=ingest).status_code == 200
    assert api.get("/v1/events", headers=ingest).status_code == 401
    assert api.get("/v1/events", headers=query).status_code == 200
    assert api.post("/v1/events", json=event(), headers=query).status_code == 401
    assert api.get("/v1/events").status_code == 401
    assert api.post("/v1/events", json=event(), headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_ingest_rejects_prohibited_metadata_without_echoing_values(monkeypatch) -> None:
    api = client(monkeypatch)
    headers = {"Authorization": "Bearer ingest-only-token"}
    root_payload = event()
    root_payload["authorization"] = "root-secret"
    for payload in (
        root_payload,
        event({"authorization": "metadata-secret"}),
        event({"details": {"access-token": "nested-secret"}}),
        event({"items": [{"raw response": "list-secret"}]}),
    ):
        response = api.post("/v1/events", json=payload, headers=headers)
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid request"}
        assert "secret" not in response.text
    accepted = api.post("/v1/events", json=event({"payment_status": "failed"}), headers=headers)
    assert accepted.status_code == 200


def test_http_body_limit_accepts_kiosk_and_rejects_oversize(monkeypatch) -> None:
    api = client(monkeypatch)
    headers = {"Authorization": "Bearer ingest-only-token", "Content-Type": "application/json"}
    assert api.post("/v1/events/batch", content=json.dumps([event({"summary": "k" * 4096})]), headers=headers).status_code == 200

    close_metadata = {"summary": "x" * (MAX_BODY_BYTES - 1024)}
    close_body = json.dumps([event(close_metadata)])
    assert len(close_body.encode()) < MAX_BODY_BYTES
    assert api.post("/v1/events/batch", content=close_body, headers=headers).status_code == 200

    oversized_body = json.dumps([event({"summary": "x" * MAX_BODY_BYTES})])
    response = api.post("/v1/events/batch", content=oversized_body, headers=headers)
    assert response.status_code == 413
    assert response.json() == {"detail": "request body too large"}
    assert "x" * 100 not in response.text
