#!/usr/bin/env bash
set -euo pipefail
umask 077

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib-backup.sh"
usage() { printf 'Usage: %s [--backup PATH] [--keep]\n' "$0" >&2; exit 2; }
backup= keep=false
while (( $# )); do
  case $1 in --backup) backup=${2:-}; shift 2 ;; --keep) keep=true; shift ;; *) usage ;; esac
done
if [[ -z $backup ]]; then
  daily_dir=${AUDIT_BACKUP_DIR:-/var/backups/citylockers-audit/daily}
  mapfile -t dumps < <(find "$daily_dir" -maxdepth 1 -type f -name 'citylockers-audit-*.dump' -printf '%f\n' | LC_ALL=C sort -r)
  (( ${#dumps[@]} > 0 )) || fail "no successful daily dump is available"
  for candidate in "${dumps[@]}"; do
    candidate_path="$daily_dir/$candidate"
    if [[ -f "$(checksum_file "$candidate_path")" ]] && (cd -- "$daily_dir" && sha256sum --check --status "$(basename -- "$(checksum_file "$candidate_path")")"); then
      backup=$candidate_path
      break
    fi
  done
  [[ -n $backup ]] || fail "no checksum-verified daily dump is available"
fi
[[ -f $backup && $backup == *.dump && $backup != *partial* && $backup != *.tmp ]] || fail "backup must be a complete .dump file"
verify_checksum "$backup"
compose exec -T "$AUDIT_POSTGRES_SERVICE" pg_restore --list < "$backup" >/dev/null
suffix=$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')
verification_db="audit_restore_verify_${suffix}"
cleanup() {
  if [[ $keep == false ]]; then compose exec -T "$AUDIT_POSTGRES_SERVICE" sh -ec 'dropdb --if-exists -U "$POSTGRES_USER" "$1"' sh "$verification_db" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT
compose exec -T "$AUDIT_POSTGRES_SERVICE" sh -ec 'createdb -U "$POSTGRES_USER" "$1"' sh "$verification_db"
compose exec -T "$AUDIT_POSTGRES_SERVICE" sh -ec 'exec pg_restore --exit-on-error --no-owner --no-privileges -U "$POSTGRES_USER" -d "$1"' sh "$verification_db" < "$backup"
compose exec -T "$AUDIT_POSTGRES_SERVICE" sh -ec 'psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -Atqc "SELECT to_regclass('\''audit.schema_migrations'\''), to_regclass('\''audit.audit_events'\''), to_regclass('\''audit.error_occurrences'\''), to_regclass('\''audit.error_definitions'\''); SELECT count(*) FROM audit.schema_migrations; SELECT count(*) FROM audit.audit_events; SELECT count(*) FROM audit.error_occurrences; SELECT count(*) FROM audit.error_definitions;"' sh "$verification_db" >/dev/null
if [[ $keep == true ]]; then printf 'Verification succeeded; retained disposable database: %s\n' "$verification_db"; else printf 'Verification succeeded; disposable database removed.\n'; fi
