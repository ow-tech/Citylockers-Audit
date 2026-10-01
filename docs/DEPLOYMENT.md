# Deployment and operations

## Architecture

```
CityLockers Worker ─┐
Khizana audit-query ├─ HTTPS → Cloudflare Tunnel → Central Audit API → private PostgreSQL
LockerGatewayBridge ┘
Kiosk events arrive through LockerGatewayBridge; kiosks do not send audit HTTP directly.
```

The Compose API host port is loopback-only by default. `cloudflared` is an opt-in Compose profile on `audit-tunnel`; it can reach `audit-api` but is not attached to `audit-internal`. PostgreSQL is attached only to the internal Docker network, has no published port, and must never be routed through Cloudflare or exposed by router forwarding.

Tunnel HTTPS does not replace application authentication: writers require `AUDIT_INGEST_TOKEN`, while Khizana's server-side query proxy requires the distinct `AUDIT_QUERY_TOKEN`. Cloudflare Access is optional defense in depth; service tokens may be added later in addition to, never instead of, these bearer tokens.

## Host prerequisites and layout

Use a supported Linux host with Docker, Docker Compose, systemd (for the supplied timers), `age`, adequate monitored disk, and these protected paths:

- application: `/opt/citylockers-audit`
- environment: `/etc/citylockers-audit/audit.env` (mode `0600`)
- backups: `/var/backups/citylockers-audit/{daily,weekly}` (mode `0700`)

`age` is required for weekly encryption; no custom cryptography fallback exists. The backup services use Docker's PostgreSQL clients, so Docker must be available to their service account.

## Initial installation

1. Copy or clone the reviewed release to `/opt/citylockers-audit`.
2. Create `/etc/citylockers-audit/audit.env`, mode `0600`, from `.env.example`; configure distinct ingest/query tokens, database credentials, release metadata, backup recipient, and any operator-managed remote-copy script.
3. Create the daily and weekly backup directories, mode `0700`.
4. Build and start PostgreSQL: `docker compose --env-file /etc/citylockers-audit/audit.env up -d --build postgres`.
5. Run migrations explicitly: `docker compose --env-file /etc/citylockers-audit/audit.env exec -T audit-api python -m app.migrate`. API startup never runs migrations.
6. Start the API: `docker compose --env-file /etc/citylockers-audit/audit.env up -d audit-api`.
7. Check `curl --fail http://127.0.0.1:8080/health`, `/ready`, and `/version`.
8. If a tunnel has already been created outside this repository, set its runtime token and start it: `docker compose --env-file /etc/citylockers-audit/audit.env --profile cloudflared up -d cloudflared`.
9. Through the final HTTPS hostname, smoke-check `/health`, `/ready`, and `/version`; then perform authenticated ingest and query smoke tests with protected tokens.
10. Install (but only after review) the supplied systemd unit files, run `systemctl daemon-reload`, enable the two timers, create a first daily backup, and run a restore verification.

No tunnel, DNS record, credentials, or units are created by this repository.

## Backups and restore verification

`scripts/backup-daily.sh` makes custom-format UTC dumps such as `citylockers-audit-20261001T030000Z.dump`, writes checksum and safe metadata companions, and prunes only successful old daily artifacts after the new dump is complete. Default local daily retention is 14 days.

`scripts/backup-weekly.sh` encrypts the newest checksum-verified daily dump with `AUDIT_BACKUP_AGE_RECIPIENT` before any optional transfer. If `AUDIT_BACKUP_REMOTE_SCRIPT` is configured, it is an executable operator-managed script called with exactly one argument: the encrypted artifact path. It is never passed plaintext. Default encrypted local weekly retention is 12 weeks; remote/provider retention is the operator's responsibility.

Run `scripts/verify-backup.sh` at least monthly and before every upgrade. It restores to a generated disposable database, checks the audit schema/migration state and readable core tables, then drops it unless `--keep` is requested. It never targets a live database. `scripts/restore-backup.sh --backup PATH --target-database NAME` requires both an explicit non-production target and `AUDIT_RESTORE_DATABASE_URL`; it refuses names resembling `citylockers_audit`, `production`, or `prod` unless the approved incident-only `--dangerous-allow-live` flag is provided.

## Upgrade and rollback

1. Confirm `/ready`.
2. Create and verify a fresh backup.
3. Fetch/build the reviewed release.
4. Stop/update the API if required, then run the explicit migration. On migration failure, stop.
5. Start/update the API; wait for `/ready`, check `/version`, and perform authenticated ingest/query smoke tests.

An audit outage must not stop booking or locker operations. Application rollback can return to a known prior image/release. Database rollback is not automatic: never use `migrate down` unless a migration was explicitly designed and tested for reversal. If compatibility is uncertain, stop and assess; restore only from a verified backup under approved incident handling.

## Disaster restore

1. Identify the incident and stop audit writers/API as appropriate.
2. Preserve the damaged database for investigation where possible.
3. Select a verified backup and verify its checksum.
4. Restore it to a disposable database and validate schema/content first.
5. Prepare a replacement live database, then restore only under approved incident authority.
6. Start the API, wait for readiness, run authenticated query/ingest smoke tests, then resume the tunnel.

Audit can remain offline during recovery without stopping operational CityLockers systems.

## Secrets and rotation

Central host secrets are PostgreSQL credentials / `AUDIT_DATABASE_URL`, `AUDIT_INGEST_TOKEN`, `AUDIT_QUERY_TOKEN`, `CLOUDFLARE_TUNNEL_TOKEN`, `AUDIT_BACKUP_AGE_RECIPIENT`, and off-machine-copy configuration. Bridge uses `AUDIT_INGEST_URL` and `AUDIT_INGEST_TOKEN`; Khizana server-side code uses `AUDIT_QUERY_URL` and `AUDIT_QUERY_TOKEN`; the CityLockers Worker uses `AUDIT_BASE_URL` and `AUDIT_INGEST_TOKEN`.

The API accepts one token of each kind today. Rotate ingest tokens in a coordinated window: schedule, change the central token, immediately change Bridge/Worker writers, and verify ingestion. Coordinate query-token rotation with Khizana's proxy. Rotate the Cloudflare tunnel token separately. Do not place any value in source control.

## Retention, capacity, and AI boundary

V1 has **no automatic deletion of live audit records**. Backup pruning affects only local backup artifacts (daily 14 days; encrypted weekly 12 weeks). Monitor database and backup disk independently; scripts fail under pressure rather than deleting database data or audit evidence.

Future AI runs may use the read-only central query API, or later a dedicated read-only PostgreSQL account. They must not mutate audit evidence, bookings, payment state, locker commands, or configuration, automatically repair systems, or sit in ingestion, query, Bridge, or locker critical paths.

## Operations checklist

Before deployment: host disk checked; environment mode checked; database volume ready; ingest/query tokens distinct; migration succeeds; backup and restore verification succeed; health/ready/version healthy; tunnel healthy; PostgreSQL not exposed; authenticated ingest/query smoke tests pass.

After deployment: Bridge ingestion is visible; a CityLockers CL test error, Partner PA test error, and sparse KS event are visible; Khizana Audit & Errors loads; backup timer is active and its next run is scheduled. These are production operator checks and are not performed by local preparation.
