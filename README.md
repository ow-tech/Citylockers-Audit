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
