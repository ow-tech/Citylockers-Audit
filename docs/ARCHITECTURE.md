# Architecture

This repository owns central audit, error, and activity-correlation storage. Its initial store is PostgreSQL outside Supabase. Producers send non-sensitive, structured data on a best-effort basis: audit-server downtime must never block normal production operations.

Authoritative rules:

1. Existing durable business activity is the primary happy-path audit source; do not duplicate it with new happy-path logging.
2. Source precedence is durable business activity, durable operational event, reliable state transition, explicit structured event/error, then raw-log parsing as a last resort.
3. Existing `event_id` chains are preserved. `trace_id` and `operation_id` layer onto them rather than replacing them.
4. Error definitions use `<SYSTEM>-<DOMAIN>-<NUMBER>`, are static rather than counters, and are never reused. Each occurrence has a separate support reference.
5. The same canonical error code must be used in user UI, partner responses where relevant, application diagnostics, audit occurrences, and Khizana operator UI.
6. Sensitive values never enter central audit storage. AI analysis is deferred and will initially be read-only.
7. Kiosk/gateway-new implementation is explicitly deferred.
