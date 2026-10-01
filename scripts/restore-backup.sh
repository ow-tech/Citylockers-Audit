#!/usr/bin/env bash
set -euo pipefail
umask 077

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib-backup.sh"
usage() { printf 'Usage: %s --backup PATH --target-database NAME [--dangerous-allow-live]\n' "$0" >&2; exit 2; }
backup= target_database= dangerous=false
while (( $# )); do
  case $1 in
    --backup) backup=${2:-}; shift 2 ;;
    --target-database) target_database=${2:-}; shift 2 ;;
    --dangerous-allow-live) dangerous=true; shift ;;
    *) usage ;;
  esac
done
[[ -n $backup && -n $target_database && -n ${AUDIT_RESTORE_DATABASE_URL:-} ]] || usage
[[ -f $backup && $backup == *.dump && $backup != *partial* && $backup != *.tmp ]] || fail "backup must be a complete .dump file"
[[ $target_database =~ ^[A-Za-z0-9_]+$ ]] || fail "target database name is unsafe"
if [[ $dangerous == false && ${target_database,,} =~ (citylockers_audit|production|prod) ]]; then
  fail "refusing a production-like target; pass --dangerous-allow-live only after approved incident review"
fi
url_database=$(python3 -c 'import os, urllib.parse; print(urllib.parse.urlparse(os.environ["AUDIT_RESTORE_DATABASE_URL"]).path.lstrip("/").split("/", 1)[0])')
[[ $url_database == "$target_database" ]] || fail "AUDIT_RESTORE_DATABASE_URL does not name the explicit target database"
verify_checksum "$backup"
compose exec -T "$AUDIT_POSTGRES_SERVICE" pg_restore --list < "$backup" >/dev/null
target_relations=$(compose exec -T -e AUDIT_RESTORE_DATABASE_URL "$AUDIT_POSTGRES_SERVICE" sh -ec 'psql "$AUDIT_RESTORE_DATABASE_URL" -Atqc "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('\''pg_catalog'\'', '\''information_schema'\'')"' | tr -d '\r\n')
[[ $target_relations == 0 ]] || fail "refusing non-empty target database; restore only into an explicitly prepared empty database"
compose exec -T -e AUDIT_RESTORE_DATABASE_URL "$AUDIT_POSTGRES_SERVICE" sh -ec 'exec pg_restore --exit-on-error --no-owner --no-privileges --dbname="$AUDIT_RESTORE_DATABASE_URL"' < "$backup"
compose exec -T -e AUDIT_RESTORE_DATABASE_URL "$AUDIT_POSTGRES_SERVICE" sh -ec 'psql "$AUDIT_RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -Atqc "SELECT to_regclass('\''audit.schema_migrations'\''), to_regclass('\''audit.audit_events'\''), to_regclass('\''audit.error_occurrences'\''), to_regclass('\''audit.error_definitions'\''); SELECT count(*) FROM audit.schema_migrations; SELECT count(*) FROM audit.audit_events; SELECT count(*) FROM audit.error_occurrences; SELECT count(*) FROM audit.error_definitions;"' >/dev/null
printf 'Restore and integrity checks succeeded for disposable target: %s\n' "$target_database"
