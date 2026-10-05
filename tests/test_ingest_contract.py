import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.contracts import AuditEvent, ErrorOccurrence, SafeContext, deterministic_adapter_event_id
from app.store.memory import MemoryAuditStore


FIXTURES = Path(__file__).parent / "fixtures"


def payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, str]]:
    monkeypatch.setenv("AUDIT_INGEST_TOKEN", "contract-ingest-token")
    monkeypatch.setattr(main, "store", MemoryAuditStore())
    return TestClient(main.app), {"Authorization": "Bearer contract-ingest-token"}


def test_canonical_fixtures_validate_against_runtime_models() -> None:
    names = (
        "explicit_ks_unlock_actuation.json",
        "explicit_br_runtime_error.json",
        "authoritative_kh_booking_created.json",
        "explicit_cl_client_error.json",
        "explicit_pa_error.json",
        "explicit_ks_uncatalogued_error.json",
    )
    events = [AuditEvent.model_validate(payload(name)) for name in names]
    assert events[2].event_id == deterministic_adapter_event_id("KH", "booking.bookings", "booking-12345", "created")
    for event in events:
        if event.source_kind == "explicit_error":
            occurrence = ErrorOccurrence.model_validate(event.metadata.model_dump(exclude_none=True))
            assert occurrence.error_code != occurrence.reference


def test_batch_is_a_top_level_array_not_a_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    api, headers = client(monkeypatch)
    accepted = api.post("/v1/events/batch", json=[payload("explicit_ks_unlock_actuation.json")], headers=headers)
    assert accepted.status_code == 200
    assert accepted.json() == {"accepted": 1, "duplicate": 0, "rejected": 0, "rejections": []}
    assert api.post("/v1/events/batch", json={"events": [payload("explicit_ks_unlock_actuation.json")]}, headers=headers).status_code == 422


def test_event_envelope_and_provenance_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    api, headers = client(monkeypatch)

    missing_system = payload("explicit_ks_unlock_actuation.json")
    missing_system.pop("system_code")
    assert api.post("/v1/events", json=missing_system, headers=headers).status_code == 422

    explicit_with_source = payload("explicit_ks_unlock_actuation.json")
    explicit_with_source["source_stream"] = "gateway.actuations"
    assert api.post("/v1/events", json=explicit_with_source, headers=headers).status_code == 422

    authoritative = api.post("/v1/events", json=payload("authoritative_kh_booking_created.json"), headers=headers)
    assert authoritative.status_code == 200

    unknown_top_level = payload("explicit_ks_unlock_actuation.json")
    unknown_top_level["attributes"] = {"result": "sent"}
    assert api.post("/v1/events", json=unknown_top_level, headers=headers).status_code == 422


def test_safe_context_is_bounded_and_prohibited_fields_are_recursively_rejected() -> None:
    event = AuditEvent.model_validate(payload("explicit_ks_unlock_actuation.json"))
    assert event.metadata.device_id == "gateway-01"
    assert event.metadata.result == "sent"
    with pytest.raises(ValidationError):
        AuditEvent.model_validate({
            "system_code": "CL", "event_type": "client.error", "occurred_at": "2026-10-03T08:00:00Z",
            "metadata": {"details": {"access-token": "never-store-this"}},
        })
    with pytest.raises(ValidationError):
        SafeContext.model_validate({"summary": "safe", "raw response": "never-store-this"})


def test_explicit_error_requires_distinct_canonical_code_and_support_reference() -> None:
    with pytest.raises(ValidationError):
        AuditEvent.model_validate({
            "system_code": "PA", "event_type": "partner.api.error", "occurred_at": "2026-10-03T08:00:00Z",
            "source_kind": "explicit_error", "metadata": {"error_code": "PA-AUTH-001", "reference": "PA-AUTH-001"},
        })
