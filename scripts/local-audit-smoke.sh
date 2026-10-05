#!/usr/bin/env bash
# Full local-only audit integration smoke.  Nothing here reads developer .env
# files, reuses containers, calls a hosted endpoint, or changes source config.
set -euo pipefail

audit_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace="$(cd "$audit_repo/.." && pwd)"
bridge_repo="$workspace/lockergatewaybridge"
khizana_repo="$workspace/khizana"
citylockers_repo="$workspace/citylockers"
keep=false
if [[ "${1:-}" == "--keep" ]]; then keep=true
elif [[ $# -gt 0 ]]; then echo "usage: $0 [--keep]" >&2; exit 2; fi

for executable in docker curl openssl; do command -v "$executable" >/dev/null || { echo "missing prerequisite: $executable" >&2; exit 2; }; done
[[ -x "$audit_repo/.venv/bin/python" ]] || { echo "missing audit virtualenv: $audit_repo/.venv/bin/python" >&2; exit 2; }
[[ -x "$bridge_repo/apps/mqtt-bridge/.venv/bin/python" ]] || { echo "missing bridge virtualenv: $bridge_repo/apps/mqtt-bridge/.venv/bin/python" >&2; exit 2; }
[[ -d "$khizana_repo/node_modules" && -d "$citylockers_repo/node_modules" ]] || { echo "Khizana and CityLockers node_modules are required; run their normal dependency install first." >&2; exit 2; }

run_dir="$(mktemp -d -t citylockers-audit-smoke.XXXXXX)"
project="citylockers-audit-smoke-$$"
compose_file="$audit_repo/scripts/local-audit-smoke.compose.yml"
env_file="$run_dir/smoke.env"
exporter_pid=""

free_port() {
  "$audit_repo/.venv/bin/python" -c 'import socket; socket_socket=socket.socket(); socket_socket.bind(("127.0.0.1", 0)); print(socket_socket.getsockname()[1]); socket_socket.close()'
}

cleanup() {
  local status=$?
  if [[ "$keep" == true ]]; then
    echo "KEEP project=$project env_file=$env_file"
  else
    [[ -n "$exporter_pid" ]] && kill "$exporter_pid" 2>/dev/null || true
    docker compose --project-name "$project" --env-file "$env_file" -f "$compose_file" down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$run_dir"
    echo "CLEANUP PASS (disposable containers, volumes, tokens, and temp files removed)"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

central_pg_port="$(free_port)"; audit_port="$(free_port)"; khizana_pg_port="$(free_port)"; mqtt_port="$(free_port)"; redis_port="$(free_port)"; export_port="$(free_port)"
central_password="$(openssl rand -hex 24)"; khizana_password="$(openssl rand -hex 24)"; ingest_token="$(openssl rand -hex 32)"; query_token="$(openssl rand -hex 32)"; export_token="$(openssl rand -hex 32)"
printf '%s\n' \
  "AUDIT_SMOKE_POSTGRES_PASSWORD=$central_password" \
  "AUDIT_SMOKE_KHIZANA_PASSWORD=$khizana_password" \
  "AUDIT_SMOKE_INGEST_TOKEN=$ingest_token" \
  "AUDIT_SMOKE_QUERY_TOKEN=$query_token" \
  "AUDIT_SMOKE_CENTRAL_PG_PORT=$central_pg_port" \
  "AUDIT_SMOKE_AUDIT_PORT=$audit_port" \
  "AUDIT_SMOKE_KHIZANA_PG_PORT=$khizana_pg_port" \
  "AUDIT_SMOKE_MQTT_PORT=$mqtt_port" \
  "AUDIT_SMOKE_REDIS_PORT=$redis_port" >"$env_file"

compose() { docker compose --project-name "$project" --env-file "$env_file" -f "$compose_file" "$@"; }
base_url="http://127.0.0.1:$audit_port"
central_database_url="postgresql://audit_smoke:$central_password@127.0.0.1:$central_pg_port/audit_smoke"
khizana_database_url="postgresql://khizana_smoke:$khizana_password@127.0.0.1:$khizana_pg_port/khizana_smoke"

compose up --detach --build
compose exec -T central-audit-api python -m app.migrate
for _ in $(seq 1 30); do curl --fail --silent "$base_url/ready" >/dev/null && break; sleep 1; done
curl --fail --silent "$base_url/health" >/dev/null
curl --fail --silent "$base_url/version" >/dev/null
compose exec -T khizana-postgres psql -U khizana_smoke -d khizana_smoke -v ON_ERROR_STOP=1 -c "CREATE TABLE booking_rows (id text PRIMARY KEY, booking_reference text NOT NULL, occurred_at timestamptz NOT NULL, source_surface text); INSERT INTO booking_rows VALUES ('kh-local-booking-001', 'SITE-SMOKE-001', '2026-10-03T12:00:00Z', 'citylockers_site');"
(cd "$khizana_repo" && npx tsx --test supabase/functions/audit-authoritative-activity-export/contract.test.ts)

KHIZANA_SMOKE_DATABASE_URL="$khizana_database_url" KHIZANA_SMOKE_EXPORT_TOKEN="$export_token" KHIZANA_SMOKE_EXPORT_PORT="$export_port" "$audit_repo/.venv/bin/python" "$audit_repo/scripts/local_audit_smoke_source.py" >"$run_dir/exporter.log" 2>&1 &
exporter_pid=$!
for _ in $(seq 1 30); do grep -q 'ready' "$run_dir/exporter.log" && break; sleep 0.1; done
grep -q 'ready' "$run_dir/exporter.log" || { cat "$run_dir/exporter.log" >&2; exit 1; }

export AUDIT_SMOKE_BASE_URL="$base_url" AUDIT_SMOKE_INGEST_TOKEN="$ingest_token" AUDIT_SMOKE_QUERY_TOKEN="$query_token" AUDIT_SMOKE_CENTRAL_DATABASE_URL="$central_database_url" AUDIT_SMOKE_EXPORT_URL="http://127.0.0.1:$export_port/functions/v1/audit-authoritative-activity-export" AUDIT_SMOKE_EXPORT_TOKEN="$export_token"
PYTHONPATH="$audit_repo" "$audit_repo/.venv/bin/python" "$audit_repo/scripts/local_audit_smoke_assert.py" collect

AUDIT_INGEST_URL="$base_url" AUDIT_INGEST_TOKEN="$ingest_token" MQTT_HOST=127.0.0.1 MQTT_PORT="$mqtt_port" AUDIT_SMOKE_MQTT_HOST=127.0.0.1 AUDIT_SMOKE_MQTT_PORT="$mqtt_port" AUDIT_SMOKE_REDIS_URL="redis://127.0.0.1:$redis_port/0" PYTHONPATH="$bridge_repo/apps/mqtt-bridge/src" "$bridge_repo/apps/mqtt-bridge/.venv/bin/python" "$audit_repo/scripts/local_audit_smoke_bridge.py"
(cd "$khizana_repo" && AUDIT_BASE_URL="$base_url" AUDIT_INGEST_TOKEN="$ingest_token" AUDIT_QUERY_TOKEN="$query_token" npm run test:partner-audit:e2e)
(cd "$citylockers_repo" && AUDIT_BASE_URL="$base_url" AUDIT_INGEST_TOKEN="$ingest_token" AUDIT_QUERY_TOKEN="$query_token" npm run test:audit:e2e)
PYTHONPATH="$audit_repo" "$audit_repo/.venv/bin/python" "$audit_repo/scripts/local_audit_smoke_assert.py" final
PYTHONPATH="$audit_repo" "$audit_repo/.venv/bin/python" "$audit_repo/scripts/local_audit_smoke_assert.py" boundaries
PYTHONPATH="$audit_repo" "$audit_repo/.venv/bin/python" "$audit_repo/scripts/local_audit_smoke_assert.py" trace

compose stop central-audit-api
AUDIT_INGEST_URL="$base_url" AUDIT_INGEST_TOKEN="$ingest_token" MQTT_HOST=127.0.0.1 MQTT_PORT="$mqtt_port" AUDIT_SMOKE_MQTT_HOST=127.0.0.1 AUDIT_SMOKE_MQTT_PORT="$mqtt_port" AUDIT_SMOKE_REDIS_URL="redis://127.0.0.1:$redis_port/0" PYTHONPATH="$bridge_repo/apps/mqtt-bridge/src" "$bridge_repo/apps/mqtt-bridge/.venv/bin/python" "$audit_repo/scripts/local_audit_smoke_bridge.py" --outage
(cd "$khizana_repo" && AUDIT_OUTAGE_ONLY=true AUDIT_BASE_URL="$base_url" AUDIT_INGEST_TOKEN="$ingest_token" AUDIT_QUERY_TOKEN="$query_token" npm run test:partner-audit:e2e)
(cd "$citylockers_repo" && AUDIT_OUTAGE_ONLY=true AUDIT_BASE_URL="$base_url" AUDIT_INGEST_TOKEN="$ingest_token" AUDIT_QUERY_TOKEN="$query_token" npm run test:audit:e2e)
compose start central-audit-api
for _ in $(seq 1 30); do curl --fail --silent "$base_url/ready" >/dev/null && break; sleep 1; done
curl --fail --silent "$base_url/ready" >/dev/null

printf '\nSYSTEM | TRIGGER | RESULT | EVENT/ERROR | TRACE | PASS\n'
printf 'KS | MQTT unlock actuation | stored | locker.unlock_actuation_sent | 00000000-0000-4000-8000-000000000202 | PASS\n'
printf 'KH | seeded durable booking | stored once | booking.created (citylockers_site) | source cursor | PASS\n'
printf 'PA | missing auth + invalid input | stored | PA-AUTH-001, PA-VALID-001 | producer correlation | PASS\n'
printf 'CL | Worker client-only error | stored | CL-APP-001 | producer correlation | PASS\n'
printf 'AU | correlated synthetic records | stable query | trace.synthetic | 00000000-0000-4000-8000-000000000101 | PASS\n'
printf 'AU | prohibited field + token split | rejected/no row | privacy + auth boundary | n/a | PASS\n'
printf 'OUTAGE | Central API stopped | non-blocking | Bridge, Partner, Worker | n/a | PASS\n'
