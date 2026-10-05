#!/usr/bin/env python3
"""Assertions and direct adapters for the disposable local audit smoke run."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.khizana_collector import KhizanaAuthoritativeCollector, KhizanaCollectorConfig
from app.store.postgres import PostgresAuditStore


BASE = os.environ["AUDIT_SMOKE_BASE_URL"].rstrip("/")
INGEST = os.environ["AUDIT_SMOKE_INGEST_TOKEN"]
QUERY = os.environ["AUDIT_SMOKE_QUERY_TOKEN"]
CENTRAL_DATABASE_URL = os.environ["AUDIT_SMOKE_CENTRAL_DATABASE_URL"]
EXPORT_URL = os.environ["AUDIT_SMOKE_EXPORT_URL"]
EXPORT_TOKEN = os.environ["AUDIT_SMOKE_EXPORT_TOKEN"]
TRACE_ID = "00000000-0000-4000-8000-000000000101"


def request(path: str, *, token: str, body: dict | None = None, method: str | None = None) -> tuple[int, dict]:
    encoded = json.dumps(body).encode() if body is not None else None
    req = Request(f"{BASE}{path}", data=encoded, method=method or ("POST" if encoded else "GET"), headers={
        "authorization": f"Bearer {token}", "content-type": "application/json",
    })
    try:
        with urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def event_count(*, system: str | None = None, event_type: str | None = None, error_code: str | None = None, search: str | None = None) -> list[dict]:
    query = "&".join(f"{key}={value}" for key, value in (("system", system), ("event_type", event_type), ("error_code", error_code), ("search", search)) if value)
    status, result = request(f"/v1/events?{query}", token=QUERY)
    require(status == 200, f"query failed: {status}")
    return result["items"]


def collect_khizana() -> None:
    store = PostgresAuditStore(CENTRAL_DATABASE_URL)
    collector = KhizanaAuthoritativeCollector(KhizanaCollectorConfig(EXPORT_URL, EXPORT_TOKEN, page_size=10), store)
    try:
        require(collector.poll_source("booking.bookings") == 1, "first Khizana collection did not ingest one row")
        require(collector.poll_source("booking.bookings") == 0, "second Khizana collection was not idempotent")
    finally:
        collector.close()
    rows = event_count(system="KH", event_type="booking.created")
    require(len(rows) == 1, "KH-02 duplicate or missing booking.created")
    require(rows[0]["attributes"].get("source_surface") == "citylockers_site", "SITE-01 provenance missing")


def boundary_assertions() -> None:
    now = datetime.now(timezone.utc).isoformat()
    private = {
        "event_id": "00000000-0000-4000-8000-000000000102", "system_code": "CL", "event_type": "privacy.probe",
        "occurred_at": now, "source_kind": "explicit_event", "metadata": {"reference": "PRIVACY-LOCAL-001", "access_code": "never-store"},
    }
    status, _ = request("/v1/events", token=INGEST, body=private)
    require(status == 422, f"privacy payload was not rejected: {status}")
    require(not event_count(search="PRIVACY-LOCAL-001"), "privacy-rejected payload created a DB row")
    status, _ = request("/v1/events", token=QUERY, body={"system_code": "CL", "event_type": "token.probe", "occurred_at": now})
    require(status == 401, f"query credential can ingest: {status}")
    status, _ = request("/v1/events", token=INGEST)
    require(status == 401, f"ingest credential can query: {status}")


def trace_assertion() -> None:
    started = datetime.now(timezone.utc).replace(microsecond=0)
    expected: list[str] = []
    for index, system in enumerate(("CL", "PA", "KS")):
        event_id = f"00000000-0000-4000-8000-00000000010{3 + index}"
        expected.append(event_id)
        payload = {"event_id": event_id, "system_code": system, "event_type": "trace.synthetic", "occurred_at": (started + timedelta(seconds=index)).isoformat(), "trace_id": TRACE_ID, "source_kind": "explicit_event", "metadata": {"summary": "local trace assertion"}}
        status, _ = request("/v1/events", token=INGEST, body=payload)
        require(status == 200, f"trace write rejected: {status}")
    status, result = request(f"/v1/traces/{TRACE_ID}", token=QUERY)
    require(status == 200, f"trace query failed: {status}")
    actual = [item["event_id"] for item in result["items"]]
    require(actual == expected, f"trace query was not exact/stable: {actual}")


def bridge_assertion() -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        rows = event_count(system="KS", event_type="locker.unlock_actuation_sent")
        if rows:
            require(len(rows) == 1, "BR-01 duplicated the KS relay")
            require(rows[0]["event_type"] != "locker.opened", "KS-01 mislabeled physical open")
            return
        time.sleep(0.2)
    raise AssertionError("KS-01/BR-01 missing relay event")


def final_assertions() -> None:
    bridge_assertion()
    require(len(event_count(system="PA", error_code="PA-AUTH-001")) == 1, "PA-01 missing or duplicated")
    require(len(event_count(system="PA", error_code="PA-VALID-001")) == 1, "PA-02 missing or duplicated")
    require(len(event_count(system="CL", error_code="CL-APP-001")) == 1, "CL-01 missing or duplicated")


def main() -> None:
    command = sys.argv[1]
    if command == "collect":
        collect_khizana()
    elif command == "boundaries":
        boundary_assertions()
    elif command == "trace":
        trace_assertion()
    elif command == "final":
        final_assertions()
    else:
        raise SystemExit(f"unknown command: {command}")
    print(f"{command}=PASS")


if __name__ == "__main__":
    main()
