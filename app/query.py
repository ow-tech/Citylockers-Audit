"""Read-only, deliberately sanitized audit query projection."""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.contracts import AuditEvent, SafeContext

MAX_LIMIT = 100
SAFE_METADATA_KEYS = frozenset({
    "error_code", "reference", "fingerprint", "endpoint", "http_status", "reason",
    "partner_id", "booking_id", "booking_reference", "transaction_id", "payment_attempt_id",
    "device_id", "wall_id", "locker_id", "terminal_id", "partner_request_id", "result",
    "summary", "service", "surface", "route", "app_version", "exception_type", "payment_status", "source_surface",
})


def bounded_limit(value: int) -> int:
    if value < 1 or value > MAX_LIMIT:
        raise HTTPException(422, f"limit must be between 1 and {MAX_LIMIT}")
    return value


def decode_cursor(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        occurred_at, event_id = urlsafe_b64decode(cursor.encode()).decode().split("\x1f", 1)
        return datetime.fromisoformat(occurred_at), event_id
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "invalid cursor") from None


def encode_cursor(event: AuditEvent) -> str:
    raw = f"{event.occurred_at.isoformat()}\x1f{event.event_id}".encode()
    return urlsafe_b64encode(raw).decode()


def safe_metadata(metadata: SafeContext | dict[str, Any]) -> dict[str, str | int]:
    values = metadata.model_dump(exclude_none=True) if isinstance(metadata, SafeContext) else metadata
    return {key: value for key, value in values.items()
            if key in SAFE_METADATA_KEYS and isinstance(value, (str, int)) and not isinstance(value, bool)}


def event_record(event: AuditEvent) -> dict[str, Any]:
    attributes = safe_metadata(event.metadata)
    return {
        "event_id": event.event_id,
        "system": event.system_code,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "trace_id": event.trace_id,
        "operation_id": event.operation_id,
        "request_id": event.request_id,
        "source_kind": event.source_kind,
        "source_system": event.source_system,
        "source_stream": event.source_stream,
        "source_record_id": event.source_record_id,
        "source_transition": event.source_transition,
        "source_occurred_at": event.source_occurred_at,
        "error_code": attributes.get("error_code"),
        "reference": attributes.get("reference"),
        "fingerprint": attributes.get("fingerprint"),
        "result": attributes.get("result"),
        "summary": attributes.get("summary") or attributes.get("reason"),
        "attributes": attributes,
    }


def matches(record: dict[str, Any], *, search: str | None, system: str | None, event_type: str | None,
            source_system: str | None, kind: str | None, error_code: str | None,
            from_at: datetime | None, to_at: datetime | None) -> bool:
    if system and record["system"] != system:
        return False
    if event_type and record["event_type"] != event_type:
        return False
    if source_system and record["source_system"] != source_system:
        return False
    if kind == "error" and record["source_kind"] != "explicit_error":
        return False
    if kind == "event" and record["source_kind"] == "explicit_error":
        return False
    if error_code and record["error_code"] != error_code:
        return False
    occurred_at = record["occurred_at"]
    if from_at and occurred_at < from_at:
        return False
    if to_at and occurred_at > to_at:
        return False
    if search:
        needle = search.casefold()
        values = [record[key] for key in ("event_id", "trace_id", "operation_id", "request_id", "error_code", "reference")]
        values.extend(record["attributes"].values())
        if not any(needle in str(value).casefold() for value in values if value is not None):
            return False
    return True


def page_events(events: list[AuditEvent], *, limit: int, cursor: str | None, **filters: Any) -> dict[str, Any]:
    after = decode_cursor(cursor)
    ordered = sorted(events, key=lambda event: (event.occurred_at, event.event_id or ""), reverse=True)
    records = [event_record(event) for event in ordered]
    records = [record for record in records if matches(record, **filters)]
    if after:
        records = [record for record in records if (record["occurred_at"], record["event_id"]) < after]
    page = records[:limit]
    next_cursor = encode_cursor(next(event for event in ordered if event.event_id == page[-1]["event_id"])) if len(records) > limit else None
    return {"items": page, "next_cursor": next_cursor}


def error_definitions() -> dict[str, dict[str, Any]]:
    path = Path(__file__).parent.parent / "contracts" / "error-catalogue.yaml"
    definitions: dict[str, dict[str, Any]] = {}
    code: str | None = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("- code: "):
            code = line.removeprefix("- code: ").strip()
        elif code and line.startswith("meaning: "):
            definitions[code] = {"code": code, "title": line.removeprefix("meaning: ").strip(), "system": code.split("-", 1)[0], "description": None, "deprecated": False}
            code = None
    return definitions


def recurrence(events: list[AuditEvent], fingerprint: str) -> dict[str, Any] | None:
    occurrences = [event for event in events if safe_metadata(event.metadata).get("fingerprint") == fingerprint]
    if not occurrences:
        return None
    times = [event.occurred_at for event in occurrences]
    return {"occurrences": len(occurrences), "first_seen": min(times), "last_seen": max(times)}
