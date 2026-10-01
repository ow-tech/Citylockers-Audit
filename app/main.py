import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import ValidationError

from app.contracts import AuditEvent
from app.query import bounded_limit, error_definitions, event_record, page_events, recurrence
from app.store.memory import MemoryAuditStore
from app.store.postgres import PostgresAuditStore

MAX_BATCH_SIZE = 100
MAX_QUERY_WINDOW = timedelta(days=31)
app = FastAPI(title="CityLockers Audit", version="0.1.0")
store = PostgresAuditStore(os.environ["DATABASE_URL"]) if os.environ.get("DATABASE_URL") else MemoryAuditStore()


def all_events() -> list[AuditEvent]:
    return store.all_events()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/v1/events")
def ingest_event(event: AuditEvent) -> dict[str, str]:
    return {"status": store.record_event(event), "event_id": event.event_id}


@app.post("/v1/events/batch")
def ingest_event_batch(events: list[dict[str, Any]]) -> dict[str, Any]:
    if len(events) > MAX_BATCH_SIZE:
        raise HTTPException(status_code=422, detail=f"batch may contain at most {MAX_BATCH_SIZE} events")
    counts = {"accepted": 0, "duplicate": 0, "rejected": 0}
    rejected = []
    for index, payload in enumerate(events):
        try:
            event = AuditEvent.model_validate(payload)
        except ValidationError:
            counts["rejected"] += 1
            rejected.append({"index": index, "code": "invalid_event"})
        else:
            counts[store.record_event(event)] += 1
    return {**counts, "rejections": rejected}


def require_query_token(authorization: str | None) -> None:
    # FastAPI normally reads headers through Header; keeping this helper isolated makes the
    # constant-time boundary explicit in tests and avoids sharing the ingest credential.
    expected = os.environ.get("AUDIT_QUERY_TOKEN")
    received = authorization.removeprefix("Bearer ") if authorization else ""
    if not expected:
        raise HTTPException(503, "read API is not configured")
    if not hmac.compare_digest(received, expected):
        raise HTTPException(401, "unauthorized")


def query_auth(authorization: str | None = None) -> None:
    require_query_token(authorization)


def bounded_dates(from_at: datetime | None, to_at: datetime | None) -> tuple[datetime, datetime]:
    end = to_at or datetime.now(timezone.utc)
    start = from_at or end - MAX_QUERY_WINDOW
    if start > end or end - start > MAX_QUERY_WINDOW:
        raise HTTPException(422, "date range must not exceed 31 days")
    return start, end


@app.get("/v1/events")
def query_events(
    authorization: str | None = Header(None), search: str | None = None,
    system: str | None = None, event_type: str | None = None, kind: Literal["error", "event"] | None = None,
    error_code: str | None = None, from_at: datetime | None = None, to_at: datetime | None = None,
    cursor: str | None = None, limit: int = 50,
) -> dict[str, Any]:
    query_auth(authorization)
    from_at, to_at = bounded_dates(from_at, to_at)
    return page_events(all_events(), limit=bounded_limit(limit), cursor=cursor, search=search,
                       system=system, event_type=event_type, kind=kind, error_code=error_code, from_at=from_at, to_at=to_at)


@app.get("/v1/errors")
def query_errors(
    authorization: str | None = Header(None), search: str | None = None, system: str | None = None,
    error_code: str | None = None, from_at: datetime | None = None, to_at: datetime | None = None,
    cursor: str | None = None, limit: int = 50,
) -> dict[str, Any]:
    query_auth(authorization)
    from_at, to_at = bounded_dates(from_at, to_at)
    return page_events(all_events(), limit=bounded_limit(limit), cursor=cursor, search=search,
                       system=system, event_type=None, kind="error", error_code=error_code, from_at=from_at, to_at=to_at)


@app.get("/v1/errors/{occurrence_id}")
def error_detail(occurrence_id: str, authorization: str | None = Header(None)) -> dict[str, Any]:
    query_auth(authorization)
    event = next((candidate for candidate in all_events() if candidate.event_id == occurrence_id), None)
    if event is None or event.source_kind != "explicit_error":
        raise HTTPException(404, "error occurrence not found")
    record = event_record(event)
    record["definition"] = error_definitions().get(record["error_code"])
    if record["fingerprint"]:
        record["recurrence"] = recurrence(all_events(), record["fingerprint"])
    return record


@app.get("/v1/error-definitions/{code}")
def error_definition(code: str, authorization: str | None = Header(None)) -> dict[str, Any]:
    query_auth(authorization)
    definition = error_definitions().get(code)
    if definition is None:
        raise HTTPException(404, "error definition not found")
    return definition


@app.get("/v1/traces/{trace_id}")
def trace(trace_id: str, authorization: str | None = Header(None), limit: int = 100) -> dict[str, Any]:
    query_auth(authorization)
    items = [event_record(event) for event in sorted(all_events(), key=lambda event: (event.occurred_at, event.event_id or "")) if event.trace_id == trace_id]
    return {"trace_id": trace_id, "items": items[:bounded_limit(limit)]}
