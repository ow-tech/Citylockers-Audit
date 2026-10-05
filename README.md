# CityLockers Audit

Central audit, error, and activity-correlation foundation for CityLockers systems.

It records observability data outside Supabase and must never block normal production operations. PostgreSQL is the initial central store. Kiosk integration and AI analysis are deliberately deferred.

Run locally:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The skeleton exposes `GET /health`.

Deployment preparation, backups, restore verification, the optional Cloudflare Tunnel profile, retention, and operational procedures are documented in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). PostgreSQL is private to Compose; the API host port defaults to loopback-only.

## Read-only operator queries

The query API exposes sanitized records at `/v1/errors`, `/v1/errors/{occurrence_id}`,
`/v1/error-definitions/{code}`, `/v1/events`, and `/v1/traces/{trace_id}`. Set
`AUDIT_QUERY_TOKEN` on this service and pass it only from Khizana's server-side
`audit-query` function. It is intentionally distinct from `AUDIT_INGEST_TOKEN`; do not
place either value in browser configuration. Khizana requires `AUDIT_QUERY_URL` and
`AUDIT_QUERY_TOKEN` server secrets. Production connectivity remains approved-network-path
deployment work.

## Khizana authoritative activity collector

Central Audit can pull Khizana's read-only `audit-authoritative-activity-export`
Edge Function without placing an audit dependency on booking, payment, or locker
operations. It is disabled unless `KHIZANA_AUDIT_COLLECTOR_ENABLED=true`; set
`KHIZANA_AUDIT_EXPORT_URL` to the full function URL and give Central Audit the
separate `KHIZANA_AUDIT_EXPORT_TOKEN`. `KHIZANA_AUDIT_POLL_INTERVAL` defaults to
30 seconds, `KHIZANA_AUDIT_PAGE_SIZE` defaults to 100 (maximum 100), and
`KHIZANA_AUDIT_REQUEST_TIMEOUT` defaults to 10 seconds.

The collector owns one `(occurred_at, record_id)` cursor per approved source in
`audit.source_checkpoints`. It saves a page cursor only after ingesting the whole
page; a retry can resend rows, and deterministic authoritative source identity
makes that idempotent. Export credentials never enter Khizana browser, booking,
payment, or device paths.
