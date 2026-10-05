# Central Audit ingest contract

This document is the implementation authority for producers. The runtime Pydantic
models in `app/contracts.py` are the source of truth; the fixtures in
`tests/fixtures/` are complete accepted examples. Ingest is best effort and must
never be made a booking, payment, gateway, or client critical-path dependency.

## Endpoint and authentication

All producer records use `POST /v1/events` (one object) or `POST /v1/events/batch`
(one top-level JSON array, at most 100 objects). Both require exactly the service's
ingest credential: `Authorization: Bearer $AUDIT_INGEST_TOKEN`. The query token is
not accepted for ingest. `{ "events": [...] }` is intentionally not an ingest
wrapper and is rejected.

## AuditEvent envelope

Every event has these fields. Unknown top-level fields are rejected.

| Field | Required | Accepted value |
| --- | --- | --- |
| `event_id` | no | Non-blank string. Explicit events receive a UUID when omitted; source events receive a deterministic UUIDv5 when omitted. |
| `system_code` | yes | `CL`, `KH`, `PA`, `BR`, `KS`, or `AU`. |
| `event_type` | yes | Non-blank string, maximum 200 characters. |
| `occurred_at` | yes | ISO-8601 datetime. |
| `trace_id`, `operation_id`, `request_id` | no | Non-blank strings. |
| `source_kind` | no | `explicit_event` (default), `explicit_error`, `business_activity`, or `operational_event`. |
| `metadata` | no | A `SafeContext` object only; its complete vocabulary is below. |

`source_system`, `source_stream`, `source_record_id`, `source_transition`, and
`source_occurred_at` are source-provenance fields. They are never a substitute for
device, booking, or correlation context.

## EXPLICIT_RUNTIME_EVENT

Use `explicit_event` for kiosk hardware evidence, Bridge runtime evidence, and other
runtime activity with no authoritative source row. Use `explicit_error` for the
same class of occurrence when it is an error. It requires `system_code` and may
include `event_id`, `trace_id`, `operation_id`, and `request_id`.

An explicit event must omit **all** authoritative source fields: `source_system`,
`source_stream`, `source_record_id`, `source_transition`, and
`source_occurred_at`. Any one of them rejects the event.

Minimal explicit runtime payload:

```json
{
  "system_code": "KS",
  "event_type": "locker.unlock_actuation_sent",
  "occurred_at": "2026-10-03T08:00:00Z",
  "source_kind": "explicit_event",
  "metadata": {"device_id": "gateway-01", "result": "sent"}
}
```

The complete canonical kiosk example is
`tests/fixtures/explicit_ks_unlock_actuation.json`.

## AUTHORITATIVE_SOURCE_EVENT

Use `business_activity` for durable Khizana business records. The current contract
also reserves `operational_event` for a durable operational source record. Both
source kinds require all five provenance fields: `source_system`, `source_stream`,
`source_record_id`, `source_transition`, and `source_occurred_at`. They must be
stable values from the durable source, not values reconstructed from a request or
client callback.

If `event_id` is omitted, Central Audit derives it deterministically from
`source_system`, `source_stream`, `source_record_id`, and `source_transition`.
Both in-memory and PostgreSQL stores deduplicate that authoritative identity; an
explicitly supplied `event_id` does not bypass it.

Minimal authoritative-source payload:

```json
{
  "system_code": "KH",
  "event_type": "booking.created",
  "occurred_at": "2026-10-03T08:02:00Z",
  "source_kind": "business_activity",
  "source_system": "KH",
  "source_stream": "booking.bookings",
  "source_record_id": "booking-12345",
  "source_transition": "created",
  "source_occurred_at": "2026-10-03T08:02:00Z"
}
```

The complete canonical Khizana example is
`tests/fixtures/authoritative_kh_booking_created.json`.

## ErrorOccurrence

There is no separate error-ingest endpoint. An error occurrence is an `AuditEvent`
with `source_kind: "explicit_error"`; its `metadata` is validated as the Pydantic
`ErrorOccurrence` model. `ErrorOccurrenceEvent` is the reusable Pydantic envelope
for schema generation and has the same wire shape as that `AuditEvent`.

`error_code` and `reference` are required, non-blank strings of at most 100
characters. `error_code` is the stable canonical catalogue code (for example
`PA-AUTH-001`). `reference` is the per-occurrence support reference shown to an
operator. They must not be equal. `fingerprint` is optional and enables recurrence
reporting. Explicit errors have the same no-authoritative-source-identity rule as
all explicit runtime events.

Minimal explicit error payload:

```json
{
  "system_code": "PA",
  "event_type": "partner.api.error",
  "occurred_at": "2026-10-03T08:04:00Z",
  "source_kind": "explicit_error",
  "metadata": {
    "error_code": "PA-AUTH-001",
    "reference": "PA-SR-20261003-001"
  }
}
```

Canonical error fixtures: `explicit_cl_client_error.json`, `explicit_pa_error.json`,
`explicit_br_runtime_error.json`, and `explicit_ks_uncatalogued_error.json`.

## SafeContext / device and entity context

`metadata` is the only accepted context location. Top-level `device_id`, `wall_id`,
`locker_id`, `terminal_id`, `booking_id`, `transaction_id`, `result`, and
`attributes` are rejected. `attributes` is not a pass-through object.

`metadata` accepts only these bounded keys: `error_code`, `reference`,
`fingerprint`, `endpoint`, `http_status`, `reason`, `partner_id`, `booking_id`,
`booking_reference`, `transaction_id`, `payment_attempt_id`, `device_id`, `wall_id`,
`locker_id`, `terminal_id`, `partner_request_id`, `result`, `summary`, `route`,
`app_version`, `payment_status`, `service`, `surface`, `exception_type`, and
`source_surface`. `source_surface` is limited to `citylockers_site`. Identifier
values are non-blank strings up to 300 characters; summaries/reasons up to 1000;
codes/references, `service`, `surface`, `app_version`, `exception_type`, `result`,
and `payment_status` up to 100; fingerprints up to 200; and `http_status` is an
integer from 100 through 599. The safe query projection currently exposes the
operator-relevant identifier, result, error, and summary fields from this vocabulary.

Nested objects, arrays, unknown keys, and prohibited sensitive keys are rejected.
Prohibited keys are checked recursively and include credentials, authorization
headers, cookies, passwords, OTPs, access codes, bearer/JWT/API tokens, card data,
merchant keys, provider evidence, and raw request/response bodies. Validation
responses deliberately do not echo submitted values.

## Required producer changes

Producers that currently send `{ "events": [...] }` must send the array itself.
Producers that send identifiers, `result`, or `attributes` at the top level must
move only supported values into `metadata` and discard unsupported data. Runtime
producers must remove source-provenance fields; durable export adapters must supply
the complete authoritative identity. Error producers must supply distinct
`metadata.error_code` and `metadata.reference`. No producer may send secrets to
make an otherwise-invalid payload pass.
