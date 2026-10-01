# PostgreSQL and HTTP boundary proof

The service limits ingress request bodies to 256 KiB (`MAX_BODY_BYTES`). This
comfortably accepts a 4 KiB kiosk relay and the maximum 100-event batch while
bounding malformed or unexpectedly large requests before JSON decoding where a
`Content-Length` is provided. Rejections return only a short generic error.

Metadata is recursively inspected at ingest. Exact normalized field names are
denied (case, hyphen, and space variants normalize to underscore); substring
matching is intentionally not used, so useful fields such as `payment_status`
remain accepted. Validation responses do not return request fragments.

## Index review

The current read API loads the bounded audit collection and performs its
sanitized projection/filtering and composite `(occurred_at, event_id)` keyset
pagination in application code. PostgreSQL therefore does not currently issue
read predicates for `occurred_at`, error metadata, trace, operation, request,
or source system from these endpoints. Adding speculative indexes for them
would not improve the implemented query path.

Existing indexes cover current database operations, with one additive lookup
index justified by the existing store query:

- `audit_events_pkey` covers `event_id` idempotency.
- `audit_events_authoritative_source_identity_unique` covers authoritative
  source identity idempotency.
- `audit_events_source_lookup_idx` covers `query_events()`'s exact source
  system/stream/record lookup and chronological return order. The partial
  uniqueness index cannot service that read because its predicate is not part
  of the read query.
- `traces_pkey`, `error_definitions_pkey`, `error_occurrences_pkey`, and
  `source_checkpoints_pkey` cover their direct lookups.

The release proof inspects this catalogue and runs `EXPLAIN` for the event ID
and source lookup paths. A future SQL-backed read-filter path
should add indexes alongside that implementation, based on its actual query
predicates.
