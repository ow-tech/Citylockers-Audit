#!/usr/bin/env python3
"""Disposable Khizana durable-row exporter used only by the local smoke harness."""

from __future__ import annotations

import json
import os
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from psycopg import connect
from psycopg.rows import dict_row


DATABASE_URL = os.environ["KHIZANA_SMOKE_DATABASE_URL"]
TOKEN = os.environ["KHIZANA_SMOKE_EXPORT_TOKEN"]


def _events(query: dict[str, list[str]]) -> list[dict[str, str | dict[str, str]]]:
    if query.get("source", [None])[0] != "booking.bookings":
        return []
    after_at, after_id = query.get("after_occurred_at", [None])[0], query.get("after_record_id", [None])[0]
    limit = min(max(int(query.get("limit", ["100"])[0]), 1), 100)
    sql = """
        SELECT id, booking_reference, occurred_at, source_surface
        FROM booking_rows
        WHERE (%s::timestamptz IS NULL OR (occurred_at, id) > (%s::timestamptz, %s))
        ORDER BY occurred_at, id LIMIT %s
    """
    with connect(DATABASE_URL, row_factory=dict_row) as database, database.cursor() as cursor:
        cursor.execute(sql, (after_at, after_at, after_id, limit))
        rows = cursor.fetchall()
    return [{
        "source_system": "KH", "source_stream": "booking.bookings", "source_record_id": row["id"],
        "source_transition": "created", "source_occurred_at": row["occurred_at"].isoformat(),
        "event_type": "booking.created", "booking_id": row["id"], "booking_reference": row["booking_reference"],
        "result": "success", "attributes": {"source_surface": "citylockers_site"} if row["source_surface"] == "citylockers_site" else {},
    } for row in rows]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler interface
        parsed = urlparse(self.path)
        if parsed.path != "/functions/v1/audit-authoritative-activity-export" or self.headers.get("x-audit-export-token") != TOKEN:
            self.send_error(HTTPStatus.UNAUTHORIZED)
            return
        body = json.dumps({"events": _events(parse_qs(parsed.query))}).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    port = int(os.environ["KHIZANA_SMOKE_EXPORT_PORT"])
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"khizana-local-exporter=ready port={port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
