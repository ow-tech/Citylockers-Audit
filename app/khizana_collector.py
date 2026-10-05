"""Pull durable Khizana activity into the central audit store.

This is deliberately a pull-only integration: Khizana never calls Central Audit on
its booking, payment, or locker paths.  A failed collector leaves its checkpoint
unchanged and is retried by the Central Audit process.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.contracts import AuditEvent, SourceCheckpoint
from app.store.base import AuditStore

LOG = logging.getLogger(__name__)

SUPPORTED_SOURCES = (
    "booking.bookings",
    "booking.transactions",
    "finance.refund_requests",
    "booking.terminal_void_operations",
    "booking.terminal_payment_attempts",
    "booking.bridge_switch_operations",
    "booking.device_installs",
    "partner.bridge_requests",
    "booking.manual_refund_marks",
)
CHECKPOINT_TYPE = "khizana.occurred_at_record_id.v1"
CHECKPOINT_PREFIX = "khizana:"


class Response(Protocol):
    def raise_for_status(self) -> None: ...
    def json(self) -> Any: ...


class HttpClient(Protocol):
    def get(self, url: str, *, headers: dict[str, str], params: dict[str, str | int], timeout: float) -> Response: ...


class _UrlResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        # urllib raises HTTPError before a response reaches this boundary.
        return None

    def json(self) -> Any:
        import json
        return json.loads(self.body)


class UrlLibHttpClient:
    """Small standard-library client; there is no producer SDK dependency."""
    def get(self, url: str, *, headers: dict[str, str], params: dict[str, str | int], timeout: float) -> Response:
        separator = "&" if "?" in url else "?"
        request = Request(f"{url}{separator}{urlencode(params)}", headers=headers, method="GET")
        with urlopen(request, timeout=timeout) as response:  # nosec B310: controlled operator URL
            return _UrlResponse(response.read())

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class KhizanaCollectorConfig:
    export_url: str
    export_token: str
    poll_interval: float = 30.0
    page_size: int = 100
    request_timeout: float = 10.0

    def __post_init__(self) -> None:
        if not self.export_url.startswith(("https://", "http://")):
            raise ValueError("KHIZANA_AUDIT_EXPORT_URL must be an HTTP(S) URL")
        if not self.export_token:
            raise ValueError("KHIZANA_AUDIT_EXPORT_TOKEN must not be empty")
        if not 1 <= self.page_size <= 100:
            raise ValueError("KHIZANA_AUDIT_PAGE_SIZE must be between 1 and 100")
        if self.poll_interval <= 0 or self.request_timeout <= 0:
            raise ValueError("Khizana collector intervals must be positive")


def configured_collector() -> KhizanaCollectorConfig | None:
    """Read the opt-in collector configuration without ever logging its token."""
    enabled = os.environ.get("KHIZANA_AUDIT_COLLECTOR_ENABLED", "false").strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("KHIZANA_AUDIT_COLLECTOR_ENABLED must be true or false")
    if enabled == "false":
        return None
    url = os.environ.get("KHIZANA_AUDIT_EXPORT_URL", "").strip()
    token = os.environ.get("KHIZANA_AUDIT_EXPORT_TOKEN", "")
    if not url or not token:
        raise ValueError("Khizana collector requires KHIZANA_AUDIT_EXPORT_URL and KHIZANA_AUDIT_EXPORT_TOKEN")
    return KhizanaCollectorConfig(
        export_url=url,
        export_token=token,
        poll_interval=float(os.environ.get("KHIZANA_AUDIT_POLL_INTERVAL", "30")),
        page_size=int(os.environ.get("KHIZANA_AUDIT_PAGE_SIZE", "100")),
        request_timeout=float(os.environ.get("KHIZANA_AUDIT_REQUEST_TIMEOUT", "10")),
    )


def _checkpoint_name(source: str) -> str:
    return f"{CHECKPOINT_PREFIX}{source}"


def _cursor(checkpoint: SourceCheckpoint | None) -> tuple[str | None, str | None]:
    if checkpoint is None:
        return None, None
    if checkpoint.cursor_type != CHECKPOINT_TYPE or not checkpoint.cursor_value:
        raise ValueError("invalid Khizana collector checkpoint")
    record_id = checkpoint.metadata.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise ValueError("invalid Khizana collector checkpoint")
    return checkpoint.cursor_value, record_id


def _text(value: object) -> str | None:
    return str(value) if value is not None else None


def event_from_export(source: str, payload: dict[str, Any]) -> AuditEvent:
    """Convert the fixed Khizana projection to the central authoritative contract."""
    if payload.get("source_system") not in {"KH", "khizana"}:
        raise ValueError("unexpected Khizana export source system")
    if payload.get("source_stream") != source:
        raise ValueError("unexpected Khizana export source stream")
    transition = payload.get("source_transition")
    record_id = payload.get("source_record_id")
    occurred_at = payload.get("source_occurred_at")
    if not all(isinstance(value, str) and value for value in (transition, record_id, occurred_at)):
        raise ValueError("Khizana export event has no authoritative cursor identity")

    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        raise ValueError("Khizana export attributes must be an object")
    source_surface = attributes.get("source_surface")
    if source_surface is not None and source_surface != "citylockers_site":
        raise ValueError("unexpected Khizana source surface")

    metadata = {
        key: value for key, value in {
            "booking_id": _text(payload.get("booking_id")),
            "booking_reference": _text(payload.get("booking_reference")),
            "transaction_id": _text(payload.get("transaction_id")),
            "payment_attempt_id": _text(payload.get("payment_attempt_id")),
            "device_id": _text(payload.get("device_id")),
            "wall_id": _text(payload.get("wall_id")),
            "locker_id": _text(payload.get("locker_id")),
            "terminal_id": _text(payload.get("terminal_id")),
            "partner_id": _text(payload.get("partner_id")),
            "partner_request_id": _text(payload.get("partner_request_id")),
            "result": _text(payload.get("result")),
            "source_surface": source_surface,
        }.items() if value is not None
    }
    return AuditEvent(
        system_code="KH",
        event_type=str(payload["event_type"]),
        occurred_at=occurred_at,
        source_kind="operational_event" if source in {"booking.bridge_switch_operations", "booking.device_installs"} else "business_activity",
        source_system="KH",
        source_stream=source,
        source_record_id=record_id,
        source_transition=transition,
        source_occurred_at=occurred_at,
        metadata=metadata,
    )


class KhizanaAuthoritativeCollector:
    def __init__(self, config: KhizanaCollectorConfig, store: AuditStore, http_client: HttpClient | None = None) -> None:
        self.config = config
        self.store = store
        self.http_client = http_client or UrlLibHttpClient()
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()  # type: ignore[union-attr]

    def poll_source(self, source: str) -> int:
        """Ingest complete bounded pages, saving only an ingested page cursor."""
        if source not in SUPPORTED_SOURCES:
            raise ValueError("unsupported Khizana collector source")
        ingested = 0
        while True:
            occurred_at, record_id = _cursor(self.store.get_checkpoint(_checkpoint_name(source)))
            params: dict[str, str | int] = {"source": source, "limit": self.config.page_size}
            if occurred_at is not None:
                params["after_occurred_at"] = occurred_at
                params["after_record_id"] = record_id or ""
            response = self.http_client.get(
                self.config.export_url,
                headers={"x-audit-export-token": self.config.export_token},
                params=params,
                timeout=self.config.request_timeout,
            )
            response.raise_for_status()
            body = response.json()
            events = body.get("events") if isinstance(body, dict) else None
            if not isinstance(events, list):
                raise ValueError("Khizana export response has no events list")
            if not events:
                return ingested
            if len(events) > self.config.page_size or not all(isinstance(item, dict) for item in events):
                raise ValueError("invalid Khizana export page")

            converted = [event_from_export(source, item) for item in events]
            last = converted[-1]
            for event in converted:
                self.store.record_event(event)
            self.store.save_checkpoint(SourceCheckpoint(
                source_name=_checkpoint_name(source),
                cursor_value=last.source_occurred_at.isoformat(),
                cursor_type=CHECKPOINT_TYPE,
                metadata={"record_id": last.source_record_id},
            ))
            ingested += len(converted)
            if len(events) < self.config.page_size:
                return ingested

    def poll_once(self) -> int:
        total = 0
        first_error: Exception | None = None
        for source in SUPPORTED_SOURCES:
            try:
                total += self.poll_source(source)
            except Exception as error:
                # A bad or unavailable source does not starve the other durable
                # streams. Its own checkpoint remains unchanged for the retry.
                LOG.exception("Khizana authoritative activity source collection failed: %s", source)
                first_error = first_error or error
        if first_error:
            raise first_error
        return total


class CollectorWorker:
    """A daemon worker whose failure is isolated to the Central Audit process."""
    def __init__(self, collector: KhizanaAuthoritativeCollector) -> None:
        self.collector = collector
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="khizana-audit-collector", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(self.collector.config.request_timeout + 1, 2))
        self.collector.close()

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self.collector.poll_once()
            except Exception:
                # No source payload, token, or provider response is retained in logs.
                LOG.exception("Khizana authoritative activity collection failed")
                delay = min(backoff, self.collector.config.poll_interval)
                backoff = min(backoff * 2, self.collector.config.poll_interval)
            else:
                delay = self.collector.config.poll_interval
                backoff = 1.0
            self._stop.wait(delay)
