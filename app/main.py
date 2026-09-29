from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import ValidationError

from app.contracts import AuditEvent
from app.store.memory import MemoryAuditStore

MAX_BATCH_SIZE = 100
app = FastAPI(title="CityLockers Audit", version="0.1.0")
store = MemoryAuditStore()


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


@app.get("/v1/events")
def query_events(source_system: str | None = Query(None), source_stream: str | None = Query(None), source_record_id: str | None = Query(None)) -> list[AuditEvent]:
    return store.query_events(source_system=source_system, source_stream=source_stream, source_record_id=source_record_id)
