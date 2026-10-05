# Local end-to-end audit smoke

Run the complete local harness from the Audit repository:

```bash
./scripts/local-audit-smoke.sh
```

It creates a new Docker Compose project with random loopback ports and random
test-only credentials. It never reads repository `.env` files, connects to a
hosted service, starts a real payment or terminal flow, or uses a developer
database. On success it prints a `SYSTEM | TRIGGER | RESULT | EVENT/ERROR |
TRACE | PASS` matrix and removes all containers, volumes, credentials, and
temporary files. Use `./scripts/local-audit-smoke.sh --keep` only when you need
to inspect that disposable run; it prints the Compose project and temp env-file
path to use for cleanup.

## Prerequisites and one-time setup

- Docker Engine with the Compose plugin, running locally.
- `curl` and `openssl`.
- Existing local dependencies for the changed producer seams: `citylockers/node_modules`,
  `khizana/node_modules`, `citylockers-audit/.venv`, and
  `lockergatewaybridge/apps/mqtt-bridge/.venv`. Install them with each
  repository's normal lockfile/virtual-environment workflow; the harness does
  not install or update dependencies.

No tokens, Cloudflare credentials, Supabase project, MQTT broker, or payment
credential is required. The harness generates credentials only inside its
temporary directory.

## What starts and what is proven

The harness starts central PostgreSQL, Central Audit API, isolated Khizana
PostgreSQL, Mosquitto, and Redis in one disposable Compose project. A small
local-only export fixture seeds exactly one durable `booking_rows` record in the
isolated Khizana PostgreSQL and exposes the same bounded export shape used by
the Central collector. The current Khizana Edge exporter contract test runs
before that fixture, then the harness calls the actual collector twice. This
keeps the smoke independent of a full local Supabase/Auth stack while retaining
the real producer's machine-secret, allowlist, cursor, and durable-provenance
contract.

For the kiosk path it creates a real Bridge MQTT client from
`lockergatewaybridge`, validates the local Redis endpoint, subscribes the
Bridge callback to Mosquitto, and publishes one realistic kiosk locker-event
message from a synthetic kiosk client. The Bridge's existing allowlisted relay
must store precisely one `KS locker.unlock_actuation_sent` record. It never
asserts or emits `locker.opened`.

Partner errors use the existing Partner Function sender harness. CityLockers
uses the actual Worker server seam. Both run against temporary Central Audit
credentials. The harness also verifies health/ready/version, credential
separation, prohibited metadata rejection with no stored row, collector
idempotency/provenance, and an exact stable trace query.

Finally it stops the Central Audit API, then runs the Bridge, Partner, and
Worker outage checks. Their producer calls must return within their bounded
timeouts and remain non-blocking. It restarts and rechecks Central readiness.

## Expected output

Each case prints `PASS`, followed by a summary similar to:

```text
SYSTEM | TRIGGER | RESULT | EVENT/ERROR | TRACE | PASS
KS | MQTT unlock actuation | stored | locker.unlock_actuation_sent | ... | PASS
KH | seeded durable booking | stored once | booking.created (citylockers_site) | ... | PASS
PA | missing auth + invalid input | stored | PA-AUTH-001, PA-VALID-001 | ... | PASS
CL | Worker client-only error | stored | CL-APP-001 | ... | PASS
```

Any absent record, duplicate, source-surface omission, token-boundary failure,
privacy failure, trace mismatch, validation rejection of a valid producer, or
outage blocking exits non-zero.

## Inspection and troubleshooting

Run with `--keep`, then use the displayed values:

```bash
docker compose --project-name <project> --env-file <env-file> \
  -f scripts/local-audit-smoke.compose.yml ps
docker compose --project-name <project> --env-file <env-file> \
  -f scripts/local-audit-smoke.compose.yml exec central-postgres \
  psql -U audit_smoke -d audit_smoke -c 'select event_id, system_code, event_type, trace_id from audit.audit_events order by occurred_at, event_id'
curl -H "Authorization: Bearer <query-token-from-env-file>" \
  http://127.0.0.1:<audit-port>/v1/events
```

To remove a kept run, use the same project/env/file values:

```bash
docker compose --project-name <project> --env-file <env-file> \
  -f scripts/local-audit-smoke.compose.yml down --volumes --remove-orphans
rm -rf <temporary-directory-containing-env-file>
```

If the script reports a missing virtual environment or `node_modules`, install
only that repository's normal dependencies and rerun. If Docker cannot pull an
image, restore local Docker/network availability; do not substitute a shared
developer database. A failed retained run can be inspected with `docker compose
logs` using the command above.

## Khizana Audit & Errors

The local harness proves Central Audit directly because it deliberately does
not boot a full local Supabase Auth/Edge/UI stack. In a separately configured
local Khizana environment, set the Function's `AUDIT_QUERY_URL` to the kept
local API URL and `AUDIT_QUERY_TOKEN` to the kept test query token, start the
normal local Khizana stack, sign in as an authorized user, and open
`/app/dashboard/audit/errors`. The page is a read-only query proxy; do not put
the query token in the browser or Vite environment.
